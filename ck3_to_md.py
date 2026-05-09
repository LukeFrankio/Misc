from __future__ import annotations

import os
import re
import zipfile
from datetime import datetime
from typing import Any


# ==========================================
# HELPER FUNCTIONS
# ==========================================


def safe_float(value: Any) -> float:
    """Safely converts a string-like value to ``float``."""
    if not value:
        return 0.0

    try:
        clean = (
            str(value)
            .replace('"', "")
            .replace("{", "")
            .replace("}", "")
            .split()[0]
        )
        return float(clean)
    except (ValueError, IndexError):
        return 0.0


def get_block_content(text: str, start_index: int) -> str | None:
    """Extracts text inside a ``{ ... }`` block starting at ``start_index``."""
    if start_index == -1:
        return None

    open_idx = text.find("{", start_index)
    if open_idx == -1:
        return None

    balance = 1
    current_idx = open_idx + 1
    text_length = len(text)

    while current_idx < text_length:
        char = text[current_idx]
        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
            if balance == 0:
                return text[open_idx + 1 : current_idx]
        current_idx += 1

    return None


def extract_key(content: str | None, key: str) -> str | None:
    """Finds ``key=value`` or ``key="value"`` within a block."""
    if not content:
        return None

    pattern = re.compile(rf'[\s\t\n]{key}=("[^"]*"|[^"\s\t\n{{}}]+)')
    match = pattern.search(content)
    if match:
        return match.group(1).replace('"', "")

    return None


def extract_list(content: str | None, key: str) -> list[str]:
    """Finds ``key={ 1 2 3 }`` style lists."""
    if not content:
        return []

    pattern = re.compile(rf'[\s\t\n]{key}={{(.*?)}}', re.DOTALL)
    match = pattern.search(content)
    if match:
        return match.group(1).strip().split()

    return []


def clean_name(raw_name: str | None) -> str:
    """Cleans up internal names like ``dynn_capet``."""
    if not raw_name:
        return "Unknown"

    cleaned = re.sub(
        r"^(dynn_|d_|c_|k_|e_|b_|trait_|game_concept_|race_|nick_)",
        "",
        raw_name,
    )
    cleaned = cleaned.replace("_", " ")
    return cleaned.title()


def as_string_list(value: Any) -> list[str]:
    """Normalizes a dynamic value into a list of strings."""
    if not isinstance(value, list):
        return []

    return [str(item) for item in value if item is not None]


# ==========================================
# DATABASE LOOKUP SYSTEM
# ==========================================


class CK3Lookup:
    def __init__(self, gamestate: str) -> None:
        self.gamestate: str = gamestate
        self.trait_map: dict[str, str] = self._build_trait_map()

    def _build_trait_map(self) -> dict[str, str]:
        print("Indexing Traits...")
        start = self.gamestate.find("traits_lookup={")
        if start == -1:
            return {}

        block = get_block_content(self.gamestate, start)
        if not block:
            return {}

        traits = re.findall(r'["\']?([\w_]+)["\']?', block)
        return {str(index): trait for index, trait in enumerate(traits)}

    def get_name_from_manager(
        self,
        manager: str,
        container: str,
        target_id: str | None,
    ) -> str:
        """Performs a manager/container lookup and returns a cleaned name."""
        if not target_id:
            return "None"

        manager_start = self.gamestate.find(f"{manager}={{")
        if manager_start == -1:
            return f"ID:{target_id}"

        chunk_size = 10_000_000
        search_area = self.gamestate[manager_start : manager_start + chunk_size]
        container_start = search_area.find(f"{container}={{")
        if container_start == -1:
            return f"ID:{target_id}"

        pattern = re.compile(rf'[\n\t\s]{target_id}={{\n')
        match = pattern.search(search_area, container_start)
        if not match:
            return f"ID:{target_id}"

        block = get_block_content(search_area, match.start())
        name = extract_key(block, "name")
        if name:
            return clean_name(name)

        return f"ID:{target_id}"

    def get_character_name(self, char_id: str | None) -> str | None:
        if not char_id:
            return None

        pattern = re.compile(rf'[\n\s]{char_id}={{\n')
        match = pattern.search(self.gamestate)
        if not match:
            return f"ID:{char_id}"

        block = get_block_content(self.gamestate, match.start())
        first_name = extract_key(block, "first_name") or "Unknown"
        nickname = extract_key(block, "nickname_text")
        dynasty_id = extract_key(block, "dynasty_house")
        dynasty_name = self.get_dynasty_name(dynasty_id)

        full_name = f"{first_name} {dynasty_name}".strip()
        if nickname:
            full_name += f" {nickname}"

        return full_name

    def get_dynasty_name(self, house_id: str | None) -> str:
        if not house_id:
            return ""

        pattern = re.compile(rf'[\n\s]{house_id}={{\n')
        match = pattern.search(self.gamestate)
        if not match:
            return ""

        block = get_block_content(self.gamestate, match.start())
        name = extract_key(block, "name")
        if name:
            return clean_name(name)

        return ""


# ==========================================
# MAIN PARSER
# ==========================================


class CK3UltimateExport:
    def __init__(self, save_path: str) -> None:
        self.save_path: str = save_path
        self.gamestate: str = ""
        self.player_id: str | None = None
        self.lookups: CK3Lookup | None = None
        self.data: dict[str, Any] = {}

    def load(self) -> None:
        print(f"Reading {self.save_path}...")
        try:
            with zipfile.ZipFile(self.save_path, "r") as archive:
                with archive.open("gamestate") as handle:
                    self.gamestate = handle.read().decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            with open(self.save_path, "r", encoding="utf-8", errors="replace") as handle:
                self.gamestate = handle.read()

        self.lookups = CK3Lookup(self.gamestate)
        print("Save loaded.")

    def find_player(self) -> bool:
        print("Locating player...")

        played_character_match = re.search(r"played_character={", self.gamestate)
        if played_character_match:
            block = get_block_content(self.gamestate, played_character_match.start())
            self.player_id = extract_key(block, "character")
            if self.player_id:
                return True

        current_players_match = re.search(r"currently_played_characters={", self.gamestate)
        if not current_players_match:
            return False

        block = get_block_content(self.gamestate, current_players_match.start())
        if not block:
            return False

        ids = block.strip().split()
        if not ids:
            return False

        self.player_id = ids[0]
        return True

    def parse_complex_resource(self, block: str | None, resource_name: str) -> float:
        """Handles ``gold={ value=X }`` or ``gold=X`` style resources."""
        if not block:
            return 0.0

        direct_value = extract_key(block, resource_name)
        if direct_value:
            return safe_float(direct_value)

        resource_block_start = block.find(f"{resource_name}={{")
        if resource_block_start == -1:
            return 0.0

        resource_block = get_block_content(block, resource_block_start)
        value = extract_key(resource_block, "value")
        if not value:
            value = extract_key(resource_block, "currency")
        if not value:
            value = extract_key(resource_block, "accumulated")

        return safe_float(value)

    def process(self) -> None:
        if not self.player_id:
            print("Error: Player ID not set.")
            return
        if self.lookups is None:
            print("Error: Lookups not initialized.")
            return

        print(f"Processing Data for ID: {self.player_id}...")
        living_start = self.gamestate.find("living={")
        pattern = re.compile(rf'[\n\t\s]{self.player_id}={{\n')
        match = pattern.search(self.gamestate, living_start)

        if not match:
            print("Error: Player not found in living block.")
            return

        content = get_block_content(self.gamestate, match.start())
        if content is None:
            print("Error: Player block could not be parsed.")
            return

        lookups = self.lookups

        self.data["First Name"] = extract_key(content, "first_name")
        self.data["Nickname"] = extract_key(content, "nickname_text")
        self.data["Birth"] = extract_key(content, "birth")
        self.data["DNA"] = extract_key(content, "dna")
        self.data["Sexuality"] = extract_key(content, "sexuality")

        print("Looking up Culture/Faith (Deep Scan)...")
        self.data["House"] = lookups.get_dynasty_name(extract_key(content, "dynasty_house"))
        self.data["Culture"] = lookups.get_name_from_manager(
            "culture_manager",
            "cultures",
            extract_key(content, "culture"),
        )
        self.data["Faith"] = lookups.get_name_from_manager(
            "religion",
            "faiths",
            extract_key(content, "faith"),
        )

        alive_start = content.find("alive_data={")
        alive_data = get_block_content(content, alive_start) if alive_start != -1 else None

        resource_source = alive_data or content
        self.data["Gold"] = self.parse_complex_resource(resource_source, "gold")
        self.data["Piety"] = self.parse_complex_resource(resource_source, "piety")
        self.data["Prestige"] = self.parse_complex_resource(resource_source, "prestige")
        self.data["Health"] = extract_key(alive_data, "health") or "Unknown"
        self.data["Fertility"] = extract_key(alive_data, "fertility") or "0"
        self.data["Kill Count"] = len(extract_list(alive_data, "kills"))

        landed_start = content.find("landed_data={")
        landed_data = get_block_content(content, landed_start) if landed_start != -1 else None
        if landed_data:
            self.data["Dread"] = extract_key(landed_data, "dread")
            self.data["Government"] = clean_name(extract_key(landed_data, "government"))
            self.data["Domain Size"] = len(extract_list(landed_data, "domain"))

        skill_start = content.find("skill={")
        skill_block = get_block_content(content, skill_start) if skill_start != -1 else None
        if skill_block:
            skill_values = skill_block.strip().split()
            keys = [
                "Diplomacy",
                "Martial",
                "Stewardship",
                "Intrigue",
                "Learning",
                "Prowess",
            ]
            for index, key in enumerate(keys):
                if index < len(skill_values):
                    self.data[f"Skill_{key}"] = skill_values[index]

        trait_ids = extract_list(content, "traits")
        self.data["Traits"] = [
            clean_name(lookups.trait_map.get(trait_id, f"ID_{trait_id}"))
            for trait_id in trait_ids
        ]
        self.data["Perks"] = [clean_name(perk) for perk in extract_list(alive_data, "perk")]

        vars_block = None
        if alive_data:
            vars_start = alive_data.find("variables={")
            vars_block = get_block_content(alive_data, vars_start) if vars_start != -1 else None

        flags: list[str] = []
        if vars_block:
            found_flags = re.findall(r"flag=([\w_]+)", vars_block)
            for flag_name in found_flags:
                if any(
                    marker in flag_name
                    for marker in [
                        "race_",
                        "vampire",
                        "immortal",
                        "witch",
                        "werewolf",
                        "dragon",
                        "born",
                        "special",
                    ]
                ):
                    flags.append(clean_name(flag_name))
        self.data["Flags"] = list(set(flags))

        print("Resolving Family...")
        family_start = content.find("family_data={")
        family_raw = get_block_content(content, family_start) if family_start != -1 else None
        if family_raw:
            self.data["Spouse"] = (
                lookups.get_character_name(extract_key(family_raw, "primary_spouse"))
                or "None"
            )
            self.data["Father"] = (
                lookups.get_character_name(extract_key(family_raw, "real_father"))
                or "Unknown"
            )

            children_names: list[str] = []
            for child_id in extract_list(family_raw, "child"):
                child_name = lookups.get_character_name(child_id)
                if child_name:
                    children_names.append(child_name)
            self.data["Children"] = children_names

    def export(self) -> None:
        print("Generating Markdown...")
        first_name = str(self.data.get("First Name") or "Unknown")
        nickname = str(self.data.get("Nickname") or "")
        display_name = f"{first_name} {nickname}".strip()
        fertility_percent = safe_float(self.data.get("Fertility")) * 100.0
        dna_value = str(self.data.get("DNA") or "None")
        traits = as_string_list(self.data.get("Traits"))
        flags = as_string_list(self.data.get("Flags"))
        perks = as_string_list(self.data.get("Perks"))
        children = as_string_list(self.data.get("Children"))

        with open("ck3_ultimate_export.md", "w", encoding="utf-8") as handle:
            handle.write(f"# {display_name}\n")
            handle.write(f"**House:** {self.data.get('House', 'Unknown')}\n\n")
            handle.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d')}\n\n")

            handle.write("## 📜 Vitality\n")
            handle.write("| Attribute | Value |\n|---|---|\n")
            handle.write(f"| **Culture** | {self.data.get('Culture')} |\n")
            handle.write(f"| **Faith** | {self.data.get('Faith')} |\n")
            handle.write(f"| **Birth** | {self.data.get('Birth')} |\n")
            handle.write(f"| **Sexuality** | {self.data.get('Sexuality', 'Heterosexual')} |\n")
            handle.write(f"| **Health** | {self.data.get('Health')} |\n")
            handle.write(f"| **Fertility** | {fertility_percent:.1f}% |\n")
            handle.write(f"| **DNA** | `{dna_value[:20]}...` |\n")

            handle.write("\n## 💰 Status\n")
            handle.write(f"- **Government:** {self.data.get('Government', 'Unknown')}\n")
            handle.write(f"- **Gold:** {self.data.get('Gold', 0):,.2f}\n")
            handle.write(f"- **Prestige:** {self.data.get('Prestige', 0):,.2f}\n")
            handle.write(f"- **Piety:** {self.data.get('Piety', 0):,.2f}\n")
            handle.write(f"- **Dread:** {safe_float(self.data.get('Dread')):,.1f}\n")
            handle.write(f"- **Kill Count:** {self.data.get('Kill Count')}\n")
            handle.write(f"- **Domain Size:** {self.data.get('Domain Size', 0)}\n")

            handle.write("\n## ⚔️ Base Skills (Unmodified)\n")
            handle.write(
                "*Note: These are the raw values stored in the save file. The game "
                "engine adds traits/gear/spouse bonuses live.* \n\n"
            )
            handle.write("| Skill | Base Value |\n|---|---|\n")
            for skill_name in [
                "Diplomacy",
                "Martial",
                "Stewardship",
                "Intrigue",
                "Learning",
                "Prowess",
            ]:
                handle.write(
                    f"| {skill_name} | {self.data.get(f'Skill_{skill_name}', 0)} |\n"
                )

            handle.write("\n## 🧠 Personality & Traits\n")
            handle.write(", ".join(traits) + "\n")

            if flags:
                handle.write("\n### ✨ Special Flags\n")
                handle.write(", ".join(flags) + "\n")

            if perks:
                handle.write("\n### 🎓 Lifestyle Perks\n")
                handle.write(", ".join(perks) + "\n")

            handle.write("\n## 🏰 Family Tree\n")
            handle.write(f"- **Father:** {self.data.get('Father')}\n")
            handle.write(f"- **Spouse:** {self.data.get('Spouse')}\n")

            if children:
                handle.write(f"### Children ({len(children)})\n")
                for child_name in children:
                    handle.write(f"- {child_name}\n")

        print("Success! 'ck3_ultimate_export.md' created.")


if __name__ == "__main__":
    default_save_path = "savegame.ck3"
    if os.path.exists(default_save_path):
        parser = CK3UltimateExport(default_save_path)
        parser.load()
        if parser.find_player():
            parser.process()
            parser.export()
    else:
        print(f"{default_save_path} not found.")
