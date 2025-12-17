import zipfile
import re
import os
from datetime import datetime

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def safe_float(value):
    """Safely converts string to float."""
    if not value: return 0.0
    try:
        clean = str(value).replace('"', '').replace('{', '').replace('}', '').split()[0]
        return float(clean)
    except (ValueError, IndexError):
        return 0.0

def get_block_content(text, start_index):
    """Extracts text inside a { block } starting at start_index."""
    if start_index == -1: return None
    open_idx = text.find('{', start_index)
    if open_idx == -1: return None
    
    balance = 1
    current_idx = open_idx + 1
    length = len(text)
    
    while current_idx < length:
        char = text[current_idx]
        if char == '{':
            balance += 1
        elif char == '}':
            balance -= 1
            if balance == 0:
                return text[open_idx+1:current_idx]
        current_idx += 1
    return None

def extract_key(content, key):
    """Finds key=value or key="value"."""
    if not content: return None
    # Regex looks for key= followed by quotes or non-whitespace
    pattern = re.compile(rf'[\s\t\n]{key}=("[^"]*"|[^"\s\t\n{{}}]+)')
    match = pattern.search(content)
    if match:
        return match.group(1).replace('"', '')
    return None

def extract_list(content, key):
    """Finds key={ 1 2 3 }."""
    if not content: return []
    pattern = re.compile(rf'[\s\t\n]{key}={{(.*?)}}', re.DOTALL)
    match = pattern.search(content)
    if match:
        return match.group(1).strip().split()
    return []

def clean_name(raw_name):
    """Cleans up internal names like 'dynn_capet'."""
    if not raw_name: return "Unknown"
    # Remove common prefixes
    clean = re.sub(r'^(dynn_|d_|c_|k_|e_|b_|trait_|game_concept_|race_|nick_)', '', raw_name)
    clean = clean.replace('_', ' ')
    return clean.title()

# ==========================================
# DATABASE LOOKUP SYSTEM
# ==========================================

class CK3Lookup:
    def __init__(self, gamestate):
        self.gamestate = gamestate
        self.trait_map = self._build_trait_map()
        
    def _build_trait_map(self):
        print("Indexing Traits...")
        start = self.gamestate.find("traits_lookup={")
        if start == -1: return {}
        block = get_block_content(self.gamestate, start)
        if not block: return {}
        traits = re.findall(r'["\']?([\w_]+)["\']?', block)
        return {str(i): t for i, t in enumerate(traits)}

    def get_name_from_manager(self, manager, container, target_id):
        """
        Generic Deep Search. 
        1. Find Manager (e.g. culture_manager)
        2. Find Container (e.g. cultures)
        3. Find ID
        """
        if not target_id: return "None"
        
        # Find Manager
        man_start = self.gamestate.find(f"{manager}={{")
        if man_start == -1: return f"ID:{target_id}"
        
        # Find Container inside Manager (search small window)
        # We grab a chunk to search to avoid reading whole file
        chunk_size = 10000000 # 10MB chunk
        search_area = self.gamestate[man_start : man_start + chunk_size]
        
        cont_start = search_area.find(f"{container}={{")
        if cont_start == -1: return f"ID:{target_id}"
        
        # Now search for ID inside the container
        # Pattern: newline/space ID={
        # We offset the regex search to start at the container
        pattern = re.compile(rf'[\n\t\s]{target_id}={{\n')
        match = pattern.search(search_area, cont_start)
        
        if match:
            block = get_block_content(search_area, match.start())
            name = extract_key(block, 'name')
            if name: return clean_name(name)
            
        return f"ID:{target_id}"

    def get_character_name(self, char_id):
        if not char_id: return None
        # Search globally for character definition
        pattern = re.compile(rf'[\n\s]{char_id}={{\n')
        match = pattern.search(self.gamestate)
        if match:
            block = get_block_content(self.gamestate, match.start())
            first = extract_key(block, 'first_name') or "Unknown"
            nick = extract_key(block, 'nickname_text')
            
            dyn_id = extract_key(block, 'dynasty_house')
            dyn_name = self.get_dynasty_name(dyn_id)
            
            full = f"{first} {dyn_name}"
            if nick: full += f" {nick}"
            return full
        return f"ID:{char_id}"

    def get_dynasty_name(self, house_id):
        if not house_id: return ""
        # Quick lookup in dynasties block
        pattern = re.compile(rf'[\n\s]{house_id}={{\n')
        # Restrict search to probable dynasties area (usually early in file)
        # But scanning whole file is safer for correctness
        match = pattern.search(self.gamestate)
        if match:
            block = get_block_content(self.gamestate, match.start())
            name = extract_key(block, 'name')
            if name: return clean_name(name)
        return ""

# ==========================================
# MAIN PARSER
# ==========================================

class CK3UltimateExport:
    def __init__(self, save_path):
        self.save_path = save_path
        self.gamestate = ""
        self.player_id = None
        self.lookups = None
        self.data = {}

    def load(self):
        print(f"Reading {self.save_path}...")
        try:
            with zipfile.ZipFile(self.save_path, 'r') as z:
                with z.open('gamestate') as f:
                    self.gamestate = f.read().decode('utf-8', errors='replace')
        except zipfile.BadZipFile:
            with open(self.save_path, 'r', encoding='utf-8', errors='replace') as f:
                self.gamestate = f.read()
        
        self.lookups = CK3Lookup(self.gamestate)
        print("Save loaded.")

    def find_player(self):
        print("Locating player...")
        # Priority 1: played_character block
        match = re.search(r'played_character={', self.gamestate)
        if match:
            block = get_block_content(self.gamestate, match.start())
            self.player_id = extract_key(block, 'character')
            if self.player_id: return True
        
        # Priority 2: List
        match = re.search(r'currently_played_characters={', self.gamestate)
        if match:
            block = get_block_content(self.gamestate, match.start())
            ids = block.strip().split()
            if ids:
                self.player_id = ids[0]
                return True
        return False

    def parse_complex_resource(self, block, resource_name):
        """Handles gold={ value=X } OR gold={ currency=X } OR gold=X."""
        # Try direct key
        val = extract_key(block, resource_name)
        if val: return safe_float(val)
        
        # Try block inside
        res_block_start = block.find(f"{resource_name}={{")
        if res_block_start != -1:
            res_block = get_block_content(block, res_block_start)
            # Try 'value', 'currency', 'accumulated'
            v = extract_key(res_block, 'value')
            if not v: v = extract_key(res_block, 'currency')
            if not v: v = extract_key(res_block, 'accumulated')
            return safe_float(v)
        return 0.0

    def process(self):
        print(f"Processing Data for ID: {self.player_id}...")
        living_start = self.gamestate.find("living={")
        pattern = re.compile(rf'[\n\t\s]{self.player_id}={{\n')
        match = pattern.search(self.gamestate, living_start)
        
        if not match:
            print("Error: Player not found in living block.")
            return

        content = get_block_content(self.gamestate, match.start())
        
        # --- Identity ---
        self.data['First Name'] = extract_key(content, 'first_name')
        self.data['Nickname'] = extract_key(content, 'nickname_text')
        self.data['Birth'] = extract_key(content, 'birth')
        self.data['DNA'] = extract_key(content, 'dna')
        self.data['Sexuality'] = extract_key(content, 'sexuality')
        
        # --- Lookups ---
        print("Looking up Culture/Faith (Deep Scan)...")
        self.data['House'] = self.lookups.get_dynasty_name(extract_key(content, 'dynasty_house'))
        self.data['Culture'] = self.lookups.get_name_from_manager('culture_manager', 'cultures', extract_key(content, 'culture'))
        self.data['Faith'] = self.lookups.get_name_from_manager('religion', 'faiths', extract_key(content, 'faith'))

        # --- Stats & Resources ---
        ad_start = content.find("alive_data={")
        alive_data = get_block_content(content, ad_start) if ad_start != -1 else None
        
        # Look in both main content and alive_data
        self.data['Gold'] = self.parse_complex_resource(alive_data, 'gold') if alive_data else self.parse_complex_resource(content, 'gold')
        self.data['Piety'] = self.parse_complex_resource(alive_data, 'piety') if alive_data else self.parse_complex_resource(content, 'piety')
        self.data['Prestige'] = self.parse_complex_resource(alive_data, 'prestige') if alive_data else self.parse_complex_resource(content, 'prestige')
        self.data['Health'] = extract_key(alive_data, 'health')
        self.data['Fertility'] = extract_key(alive_data, 'fertility')
        
        # Kills
        kill_ids = extract_list(alive_data, 'kills')
        self.data['Kill Count'] = len(kill_ids)

        # --- Landed Data (Dread/Gov) ---
        ld_start = content.find("landed_data={")
        landed_data = get_block_content(content, ld_start) if ld_start != -1 else None
        if landed_data:
            self.data['Dread'] = extract_key(landed_data, 'dread')
            self.data['Government'] = clean_name(extract_key(landed_data, 'government'))
            self.data['Domain Size'] = len(extract_list(landed_data, 'domain'))

        # --- Skills (Base) ---
        # Note: These are BASE skills. Total is calculated by game engine.
        skill_block = get_block_content(content, content.find("skill={"))
        if skill_block:
            s = skill_block.strip().split()
            keys = ["Diplomacy", "Martial", "Stewardship", "Intrigue", "Learning", "Prowess"]
            for i, k in enumerate(keys):
                if i < len(s): self.data[f"Skill_{k}"] = s[i]

        # --- Traits ---
        trait_ids = extract_list(content, 'traits')
        self.data['Traits'] = [clean_name(self.lookups.trait_map.get(tid, f"ID_{tid}")) for tid in trait_ids]

        # --- Perks ---
        self.data['Perks'] = [clean_name(p) for p in extract_list(alive_data, 'perk')]

        # --- Flags & Variables ---
        # Extract interesting flags from variables block
        vars_block = get_block_content(alive_data, alive_data.find("variables={"))
        flags = []
        if vars_block:
            # Regex to find flag=flag_name
            found_flags = re.findall(r'flag=([\w_]+)', vars_block)
            # Filter out boring technical flags
            for f in found_flags:
                if any(x in f for x in ['race_', 'vampire', 'immortal', 'witch', 'werewolf', 'dragon', 'born', 'special']):
                    flags.append(clean_name(f))
        self.data['Flags'] = list(set(flags)) # Unique

        # --- Family ---
        print("Resolving Family...")
        fam_raw = get_block_content(content, content.find("family_data={"))
        if fam_raw:
            self.data['Spouse'] = self.lookups.get_character_name(extract_key(fam_raw, 'primary_spouse')) or "None"
            self.data['Father'] = self.lookups.get_character_name(extract_key(fam_raw, 'real_father')) or "Unknown"
            
            children = extract_list(fam_raw, 'child')
            self.data['Children'] = []
            for cid in children:
                self.data['Children'].append(self.lookups.get_character_name(cid))

    def export(self):
        print("Generating Markdown...")
        name = f"{self.data.get('First Name', 'Unknown')} {self.data.get('Nickname', '')}".strip()
        
        with open('ck3_ultimate_export.md', 'w', encoding='utf-8') as f:
            f.write(f"# {name}\n")
            f.write(f"**House:** {self.data.get('House', 'Unknown')}\n\n")
            f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d')}\n\n")
            
            f.write("## 📜 Vitality\n")
            f.write("| Attribute | Value |\n|---|---|\n")
            f.write(f"| **Culture** | {self.data.get('Culture')} |\n")
            f.write(f"| **Faith** | {self.data.get('Faith')} |\n")
            f.write(f"| **Birth** | {self.data.get('Birth')} |\n")
            f.write(f"| **Sexuality** | {self.data.get('Sexuality', 'Heterosexual')} |\n")
            f.write(f"| **Health** | {self.data.get('Health')} |\n")
            f.write(f"| **Fertility** | {float(self.data.get('Fertility', 0))*100:.1f}% |\n")
            f.write(f"| **DNA** | `{self.data.get('DNA', 'None')[:20]}...` |\n")

            f.write("\n## 💰 Status\n")
            f.write(f"- **Government:** {self.data.get('Government', 'Unknown')}\n")
            f.write(f"- **Gold:** {self.data.get('Gold', 0):,.2f}\n")
            f.write(f"- **Prestige:** {self.data.get('Prestige', 0):,.2f}\n")
            f.write(f"- **Piety:** {self.data.get('Piety', 0):,.2f}\n")
            f.write(f"- **Dread:** {safe_float(self.data.get('Dread')):,.1f}\n")
            f.write(f"- **Kill Count:** {self.data.get('Kill Count')}\n")
            f.write(f"- **Domain Size:** {self.data.get('Domain Size', 0)}\n")
            
            f.write("\n## ⚔️ Base Skills (Unmodified)\n")
            f.write("*Note: These are the raw values stored in the save file. The game engine adds traits/gear/spouse bonuses live.* \n\n")
            f.write("| Skill | Base Value |\n|---|---|\n")
            skills = ["Diplomacy", "Martial", "Stewardship", "Intrigue", "Learning", "Prowess"]
            for s in skills:
                f.write(f"| {s} | {self.data.get(f'Skill_{s}', 0)} |\n")

            f.write("\n## 🧠 Personality & Traits\n")
            f.write(", ".join(self.data.get('Traits', [])) + "\n")

            if self.data.get('Flags'):
                f.write("\n### ✨ Special Flags\n")
                f.write(", ".join(self.data.get('Flags', [])) + "\n")
            
            if self.data.get('Perks'):
                f.write("\n### 🎓 Lifestyle Perks\n")
                f.write(", ".join(self.data.get('Perks', [])) + "\n")

            f.write("\n## 🏰 Family Tree\n")
            f.write(f"- **Father:** {self.data.get('Father')}\n")
            f.write(f"- **Spouse:** {self.data.get('Spouse')}\n")
            
            kids = self.data.get('Children', [])
            if kids:
                f.write(f"### Children ({len(kids)})\n")
                for k in kids:
                    f.write(f"- {k}\n")

        print("Success! 'ck3_ultimate_export.md' created.")

if __name__ == "__main__":
    SAVE = "savegame.ck3"
    if os.path.exists(SAVE):
        p = CK3UltimateExport(SAVE)
        p.load()
        if p.find_player():
            p.process()
            p.export()
    else:
        print(f"{SAVE} not found.")