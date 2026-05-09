from __future__ import annotations

# NOTE: Matplotlib's runtime import works in the selected Python 3.14
# environment, but its typing surface is still incomplete enough here that
# Pylance reports a pile of `unknown` noise for the plotting objects. We scope
# the relaxation to this GUI file only so the rest of the repo can stay strict.
# pyright: reportMissingModuleSource=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUnknownLambdaType=false

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from convective_heat_model import (
    AirProperties,
    ConvectionCase,
    ConvectionInputs,
    ConvectionResult,
    compute_case,
    generate_velocity_sweep,
)


@dataclass(frozen=True, slots=True)
class SliderWidgets:
    frame: ttk.Frame
    label: ttk.Label
    value_label: ttk.Label
    scale: tk.Scale


@dataclass(frozen=True, slots=True)
class CaseMetadata:
    title: str
    characteristic_label: str
    area_label: str
    uses_flow_length: bool
    flow_length_label: str


CASE_OPTIONS: tuple[tuple[str, ConvectionCase], ...] = (
    ("Placa plana", ConvectionCase.FLAT_PLATE),
    ("Cilindro em crossflow", ConvectionCase.CYLINDER_CROSSFLOW),
    ("Esfera em crossflow", ConvectionCase.SPHERE_CROSSFLOW),
    ("Tubo circular interno", ConvectionCase.INTERNAL_TUBE),
)

CASE_METADATA: dict[ConvectionCase, CaseMetadata] = {
    ConvectionCase.FLAT_PLATE: CaseMetadata(
        title="Placa plana em escoamento externo",
        characteristic_label="Comprimento da placa L (m)",
        area_label="Área de troca térmica A (m²)",
        uses_flow_length=False,
        flow_length_label="Comprimento do escoamento (não usado)",
    ),
    ConvectionCase.CYLINDER_CROSSFLOW: CaseMetadata(
        title="Cilindro em escoamento cruzado",
        characteristic_label="Diâmetro do cilindro D (m)",
        area_label="Área de troca térmica A (m²)",
        uses_flow_length=False,
        flow_length_label="Comprimento do escoamento (não usado)",
    ),
    ConvectionCase.SPHERE_CROSSFLOW: CaseMetadata(
        title="Esfera em escoamento cruzado",
        characteristic_label="Diâmetro da esfera D (m)",
        area_label="Área de troca térmica A (m²)",
        uses_flow_length=False,
        flow_length_label="Comprimento do escoamento (não usado)",
    ),
    ConvectionCase.INTERNAL_TUBE: CaseMetadata(
        title="Escoamento interno em tubo circular",
        characteristic_label="Diâmetro interno D (m)",
        area_label="Área molhada de troca térmica A (m²)",
        uses_flow_length=True,
        flow_length_label="Comprimento do tubo L (m)",
    ),
}


class ConvectiveHeatGUI:
    """Interactive convection workbench backed by the tested model layer."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Convection Workbench: h e transferência de calor")
        self.pending_update_id: str | None = None

        self.case_var = tk.StringVar(value=ConvectionCase.FLAT_PLATE.value)
        self.auto_properties_var = tk.BooleanVar(value=True)

        self.params: dict[str, tk.DoubleVar] = {
            "velocity": tk.DoubleVar(value=2.0),
            "characteristic_length": tk.DoubleVar(value=0.5),
            "flow_length": tk.DoubleVar(value=1.0),
            "area": tk.DoubleVar(value=1.0),
            "surface_temperature": tk.DoubleVar(value=60.0),
            "ambient_temperature": tk.DoubleVar(value=25.0),
            "rho": tk.DoubleVar(value=1.18),
            "mu": tk.DoubleVar(value=1.9e-5),
            "k": tk.DoubleVar(value=0.027),
            "cp": tk.DoubleVar(value=1007.0),
        }
        self.result_vars: dict[str, tk.StringVar] = {
            "Re": tk.StringVar(value="--"),
            "Pr": tk.StringVar(value="--"),
            "Nu": tk.StringVar(value="--"),
            "h": tk.StringVar(value="--"),
            "q": tk.StringVar(value="--"),
            "correlation": tk.StringVar(value="--"),
            "regime": tk.StringVar(value="--"),
            "property_source": tk.StringVar(value="--"),
            "film_temperature": tk.StringVar(value="--"),
            "rho": tk.StringVar(value="--"),
            "mu": tk.StringVar(value="--"),
            "k": tk.StringVar(value="--"),
            "cp": tk.StringVar(value="--"),
            "warnings": tk.StringVar(value="Aguardando cálculo."),
        }

        self.build_ui()
        self.sync_case_ui()
        self.sync_property_mode_ui()
        self.update_all()

    def build_ui(self) -> None:
        """Build the widget tree and the Matplotlib figure shell."""
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        controls = ttk.LabelFrame(main, text="Configuração do caso", padding=10)
        controls.pack(side="left", fill="y")

        ttk.Label(controls, text="Caso convectivo").pack(anchor="w")
        self.case_selector = ttk.Combobox(
            controls,
            state="readonly",
            values=[label for label, _ in CASE_OPTIONS],
            width=30,
        )
        self.case_selector.current(0)
        self.case_selector.pack(fill="x", pady=(2, 8))
        self.case_selector.bind("<<ComboboxSelected>>", self.on_case_changed)

        self.velocity_widgets = self.add_slider(
            controls,
            "Velocidade média do escoamento v (m/s)",
            "velocity",
            0.1,
            25.0,
        )
        self.characteristic_widgets = self.add_slider(
            controls,
            "Comprimento característico (m)",
            "characteristic_length",
            0.01,
            2.0,
        )
        self.flow_length_widgets = self.add_slider(
            controls,
            "Comprimento do tubo L (m)",
            "flow_length",
            0.05,
            5.0,
        )
        self.area_widgets = self.add_slider(
            controls,
            "Área de troca térmica A (m²)",
            "area",
            0.01,
            10.0,
        )
        self.surface_temperature_widgets = self.add_slider(
            controls,
            "Temperatura da superfície Ts (°C)",
            "surface_temperature",
            -20.0,
            250.0,
        )
        self.ambient_temperature_widgets = self.add_slider(
            controls,
            "Temperatura do fluido T∞ (°C)",
            "ambient_temperature",
            -40.0,
            150.0,
        )

        property_frame = ttk.LabelFrame(controls, text="Propriedades do ar", padding=8)
        property_frame.pack(fill="x", pady=(10, 0))

        ttk.Checkbutton(
            property_frame,
            text="Usar propriedades automáticas do ar (T de filme)",
            variable=self.auto_properties_var,
            command=self.on_property_mode_changed,
        ).pack(anchor="w", pady=(0, 6))

        self.rho_widgets = self.add_slider(property_frame, "Densidade ρ (kg/m³)", "rho", 0.5, 2.0)
        self.mu_widgets = self.add_slider(property_frame, "Viscosidade dinâmica μ (Pa·s)", "mu", 1.0e-5, 4.0e-5)
        self.k_widgets = self.add_slider(property_frame, "Condutividade k (W/m·K)", "k", 0.01, 0.08)
        self.cp_widgets = self.add_slider(property_frame, "Calor específico cp (J/kg·K)", "cp", 800.0, 1300.0)
        self.manual_property_widgets = [
            self.rho_widgets,
            self.mu_widgets,
            self.k_widgets,
            self.cp_widgets,
        ]

        right_side = ttk.Frame(main)
        right_side.pack(side="right", fill="both", expand=True, padx=(10, 0))

        results = ttk.LabelFrame(right_side, text="Resultados e estado do modelo", padding=10)
        results.pack(fill="x")

        result_rows = (
            ("Número de Reynolds (Re)", "Re"),
            ("Número de Prandtl (Pr)", "Pr"),
            ("Número de Nusselt (Nu)", "Nu"),
            ("Coeficiente convectivo h (W/m²·K)", "h"),
            ("Taxa de calor q (W)", "q"),
            ("Correlação ativa", "correlation"),
            ("Regime interpretado", "regime"),
            ("Fonte das propriedades", "property_source"),
            ("Temperatura de filme (°C)", "film_temperature"),
            ("ρ resolvida (kg/m³)", "rho"),
            ("μ resolvida (Pa·s)", "mu"),
            ("k resolvida (W/m·K)", "k"),
            ("cp resolvido (J/kg·K)", "cp"),
        )
        for label_text, key in result_rows:
            row = ttk.Frame(results)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label_text).pack(side="left")
            ttk.Label(
                row,
                textvariable=self.result_vars[key],
                font=("TkDefaultFont", 10, "bold"),
                wraplength=360,
                justify="right",
            ).pack(side="right")

        warnings_frame = ttk.LabelFrame(right_side, text="Validade e avisos", padding=10)
        warnings_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(
            warnings_frame,
            textvariable=self.result_vars["warnings"],
            wraplength=640,
            justify="left",
        ).pack(fill="x")

        plot_frame = ttk.LabelFrame(right_side, text="Gráficos", padding=10)
        plot_frame.pack(fill="both", expand=True, pady=(10, 0))

        fig, axes = plt.subplots(2, 1, figsize=(7.2, 6.2))
        self.fig = fig
        self.ax1 = axes[0]
        self.ax2 = axes[1]
        self.h_line = self.ax1.plot([], [], color="tab:blue", label="h (W/m²·K)")[0]
        self.h_marker = self.ax1.scatter([], [], color="red", zorder=3)
        self.q_line = self.ax2.plot([], [], color="tab:orange", label="q (W)")[0]
        self.q_marker = self.ax2.scatter([], [], color="red", zorder=3)
        self.fig.tight_layout(pad=3.0)

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def add_slider(
        self,
        parent: ttk.Frame | ttk.LabelFrame,
        label_text: str,
        key: str,
        min_value: float,
        max_value: float,
    ) -> SliderWidgets:
        """Create a labeled slider tied to a Tk variable."""
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=4)

        label = ttk.Label(frame, text=label_text)
        label.pack(anchor="w")

        value_label = ttk.Label(frame, text=f"{self.params[key].get():.5g}")
        value_label.pack(anchor="e")

        def on_change(raw_value: str) -> None:
            value_label.config(text=f"{float(raw_value):.5g}")
            self.schedule_update()

        scale = tk.Scale(
            frame,
            variable=self.params[key],
            from_=min_value,
            to=max_value,
            orient="horizontal",
            resolution=(max_value - min_value) / 500.0,
            command=on_change,
            length=300,
        )
        scale.pack(fill="x")
        return SliderWidgets(frame=frame, label=label, value_label=value_label, scale=scale)

    def current_case(self) -> ConvectionCase:
        """Return the selected convection model."""
        return ConvectionCase(self.case_var.get())

    def on_case_changed(self, _event: object) -> None:
        """Handle case-selector changes."""
        selected_label = self.case_selector.get()
        for label, case in CASE_OPTIONS:
            if label == selected_label:
                self.case_var.set(case.value)
                break
        self.sync_case_ui()
        self.schedule_update()

    def on_property_mode_changed(self) -> None:
        """Switch between automatic and manual property modes."""
        self.sync_property_mode_ui()
        self.schedule_update()

    def sync_case_ui(self) -> None:
        """Update labels and visibility for the active case."""
        metadata = CASE_METADATA[self.current_case()]
        self.root.title(f"Convection Workbench: {metadata.title}")
        self.characteristic_widgets.label.config(text=metadata.characteristic_label)
        self.area_widgets.label.config(text=metadata.area_label)
        self.flow_length_widgets.label.config(text=metadata.flow_length_label)

        if metadata.uses_flow_length:
            self.flow_length_widgets.frame.pack(fill="x", pady=4, before=self.area_widgets.frame)
            self.flow_length_widgets.scale.configure(state="normal")
        else:
            self.flow_length_widgets.frame.pack_forget()
            self.flow_length_widgets.scale.configure(state="disabled")

    def sync_property_mode_ui(self) -> None:
        """Enable or disable manual property controls."""
        target_state = "disabled" if self.auto_properties_var.get() else "normal"
        for widgets in self.manual_property_widgets:
            widgets.scale.configure(state=target_state)

    def schedule_update(self) -> None:
        """Debounce rapid updates to keep plotting responsive."""
        if self.pending_update_id is not None:
            self.root.after_cancel(self.pending_update_id)
        self.pending_update_id = self.root.after(50, self.update_all)

    def build_inputs(self) -> ConvectionInputs:
        """Translate widget state into a typed model input."""
        surface_temperature = self.params["surface_temperature"].get()
        ambient_temperature = self.params["ambient_temperature"].get()
        auto_properties = self.auto_properties_var.get()

        manual_properties: AirProperties | None = None
        if not auto_properties:
            manual_properties = AirProperties(
                rho_kg_per_m3=self.params["rho"].get(),
                mu_pa_s=self.params["mu"].get(),
                k_w_per_mk=self.params["k"].get(),
                cp_j_per_kgk=self.params["cp"].get(),
                film_temperature_c=0.5 * (surface_temperature + ambient_temperature),
                source_label="manual override",
            )

        characteristic_length = self.params["characteristic_length"].get()
        flow_length = (
            self.params["flow_length"].get()
            if CASE_METADATA[self.current_case()].uses_flow_length
            else characteristic_length
        )

        return ConvectionInputs(
            case=self.current_case(),
            velocity_m_per_s=self.params["velocity"].get(),
            characteristic_length_m=characteristic_length,
            flow_length_m=flow_length,
            area_m2=self.params["area"].get(),
            surface_temperature_c=surface_temperature,
            ambient_temperature_c=ambient_temperature,
            auto_properties=auto_properties,
            air_properties=manual_properties,
        )

    def update_all(self) -> None:
        """Recompute the current state and refresh the plots."""
        self.pending_update_id = None
        try:
            inputs = self.build_inputs()
            result = compute_case(inputs)
        except ValueError as error:
            self.populate_error_state(str(error))
            return

        self.populate_result_state(result)
        self.update_plots(inputs, result)

    def populate_error_state(self, message: str) -> None:
        """Show a soft error instead of crashing the interface."""
        for key, variable in self.result_vars.items():
            if key == "warnings":
                continue
            variable.set("--")
        self.result_vars["warnings"].set(f"Entrada inválida: {message}")
        self.canvas.draw_idle()

    def populate_result_state(self, result: ConvectionResult) -> None:
        """Push the latest model results into the UI string variables."""
        self.result_vars["Re"].set(f"{result.reynolds_number:,.2f}")
        self.result_vars["Pr"].set(f"{result.prandtl_number:.4f}")
        self.result_vars["Nu"].set(f"{result.nusselt_number:,.2f}")
        self.result_vars["h"].set(f"{result.heat_transfer_coefficient_w_per_m2k:,.2f}")
        self.result_vars["q"].set(f"{result.heat_transfer_rate_w:,.2f}")
        self.result_vars["correlation"].set(result.correlation_name)
        self.result_vars["regime"].set(result.regime_name)
        self.result_vars["property_source"].set(result.air_properties.source_label)
        self.result_vars["film_temperature"].set(f"{result.air_properties.film_temperature_c:.2f}")
        self.result_vars["rho"].set(f"{result.air_properties.rho_kg_per_m3:.4f}")
        self.result_vars["mu"].set(f"{result.air_properties.mu_pa_s:.6g}")
        self.result_vars["k"].set(f"{result.air_properties.k_w_per_mk:.5f}")
        self.result_vars["cp"].set(f"{result.air_properties.cp_j_per_kgk:.2f}")
        if result.warnings:
            self.result_vars["warnings"].set("\n• " + "\n• ".join(result.warnings))
        else:
            self.result_vars["warnings"].set("Dentro das faixas de validade preferidas para o caso atual.")

    def update_plots(self, inputs: ConvectionInputs, result: ConvectionResult) -> None:
        """Update both response plots using the pure sweep helper."""
        sweep = generate_velocity_sweep(inputs, v_min=0.1, v_max=20.0, points=200)
        case_title = CASE_METADATA[inputs.case].title

        self.h_line.set_data(sweep.velocities_m_per_s, sweep.heat_transfer_coefficients_w_per_m2k)
        self.h_marker.set_offsets(
            [[inputs.velocity_m_per_s, result.heat_transfer_coefficient_w_per_m2k]]
        )
        self.ax1.relim()
        self.ax1.autoscale_view()
        self.ax1.set_title(f"h vs velocidade — {case_title}")
        self.ax1.set_xlabel("Velocidade média do escoamento (m/s)")
        self.ax1.set_ylabel("h (W/m²·K)")
        self.ax1.grid(True)
        self.ax1.legend(loc="best")

        self.q_line.set_data(sweep.velocities_m_per_s, sweep.heat_transfer_rates_w)
        self.q_marker.set_offsets([[inputs.velocity_m_per_s, result.heat_transfer_rate_w]])
        self.ax2.relim()
        self.ax2.autoscale_view()
        self.ax2.set_title(f"q vs velocidade — {case_title}")
        self.ax2.set_xlabel("Velocidade média do escoamento (m/s)")
        self.ax2.set_ylabel("q (W)")
        self.ax2.grid(True)
        self.ax2.legend(loc="best")

        self.fig.tight_layout(pad=3.0)
        self.canvas.draw_idle()


if __name__ == "__main__":
    app_root = tk.Tk()
    app = ConvectiveHeatGUI(app_root)
    app_root.mainloop()
