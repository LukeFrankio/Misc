from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import math

ATM_PRESSURE_PA = 101_325.0
AIR_GAS_CONSTANT_J_PER_KG_K = 287.058
SUTHERLAND_CONSTANT_K = 110.4
SUTHERLAND_FACTOR = 1.458e-6
AUTO_PROPERTY_MIN_TEMP_C = -20.0
AUTO_PROPERTY_MAX_TEMP_C = 200.0


class ConvectionCase(StrEnum):
    FLAT_PLATE = "flat_plate"
    CYLINDER_CROSSFLOW = "cylinder_crossflow"
    SPHERE_CROSSFLOW = "sphere_crossflow"
    INTERNAL_TUBE = "internal_tube"


@dataclass(frozen=True, slots=True)
class AirProperties:
    rho_kg_per_m3: float
    mu_pa_s: float
    k_w_per_mk: float
    cp_j_per_kgk: float
    film_temperature_c: float
    source_label: str

    @property
    def prandtl_number(self) -> float:
        return self.cp_j_per_kgk * self.mu_pa_s / self.k_w_per_mk

    @property
    def kinematic_viscosity_m2_per_s(self) -> float:
        return self.mu_pa_s / self.rho_kg_per_m3


@dataclass(frozen=True, slots=True)
class ConvectionInputs:
    case: ConvectionCase
    velocity_m_per_s: float
    characteristic_length_m: float
    flow_length_m: float
    area_m2: float
    surface_temperature_c: float
    ambient_temperature_c: float
    auto_properties: bool = True
    air_properties: AirProperties | None = None

    def with_velocity(self, velocity_m_per_s: float) -> ConvectionInputs:
        return replace(self, velocity_m_per_s=velocity_m_per_s)


@dataclass(slots=True)
class ConvectionResult:
    air_properties: AirProperties
    reynolds_number: float
    prandtl_number: float
    nusselt_number: float
    heat_transfer_coefficient_w_per_m2k: float
    heat_transfer_rate_w: float
    warnings: list[str] = field(default_factory=list)
    correlation_name: str = ""
    regime_name: str = ""


@dataclass(frozen=True, slots=True)
class VelocitySweepResult:
    velocities_m_per_s: list[float]
    heat_transfer_coefficients_w_per_m2k: list[float]
    heat_transfer_rates_w: list[float]


@dataclass(frozen=True, slots=True)
class _CorrelationOutcome:
    nusselt_number: float
    warnings: list[str]
    correlation_name: str
    regime_name: str


def _film_temperature_c(surface_temperature_c: float, ambient_temperature_c: float) -> float:
    return 0.5 * (surface_temperature_c + ambient_temperature_c)


def _temperature_k(temperature_c: float) -> float:
    return temperature_c + 273.15


def _dynamic_viscosity_air_pa_s(temperature_c: float) -> float:
    temperature_k = _temperature_k(temperature_c)
    return SUTHERLAND_FACTOR * temperature_k**1.5 / (temperature_k + SUTHERLAND_CONSTANT_K)


def _thermal_conductivity_air_w_per_mk(temperature_c: float) -> float:
    temperature_k = _temperature_k(temperature_c)
    return 0.0241 * (temperature_k / 273.15) ** 0.9


def _specific_heat_air_j_per_kgk(temperature_c: float) -> float:
    temperature_k = _temperature_k(temperature_c)
    return 1006.0 + 0.1 * (temperature_k - 300.0)


def compute_air_properties(surface_temperature_c: float, ambient_temperature_c: float) -> AirProperties:
    film_temperature_c = _film_temperature_c(surface_temperature_c, ambient_temperature_c)
    film_temperature_k = _temperature_k(film_temperature_c)
    rho_kg_per_m3 = ATM_PRESSURE_PA / (AIR_GAS_CONSTANT_J_PER_KG_K * film_temperature_k)
    mu_pa_s = _dynamic_viscosity_air_pa_s(film_temperature_c)
    k_w_per_mk = _thermal_conductivity_air_w_per_mk(film_temperature_c)
    cp_j_per_kgk = _specific_heat_air_j_per_kgk(film_temperature_c)
    return AirProperties(
        rho_kg_per_m3=rho_kg_per_m3,
        mu_pa_s=mu_pa_s,
        k_w_per_mk=k_w_per_mk,
        cp_j_per_kgk=cp_j_per_kgk,
        film_temperature_c=film_temperature_c,
        source_label="automatic air properties",
    )


def _validate_air_properties(properties: AirProperties) -> None:
    if properties.rho_kg_per_m3 <= 0.0:
        raise ValueError("density must be positive")
    if properties.mu_pa_s <= 0.0:
        raise ValueError("dynamic viscosity must be positive")
    if properties.k_w_per_mk <= 0.0:
        raise ValueError("thermal conductivity must be positive")
    if properties.cp_j_per_kgk <= 0.0:
        raise ValueError("specific heat must be positive")



def _resolve_air_properties(inputs: ConvectionInputs) -> tuple[AirProperties, list[str]]:
    if inputs.auto_properties:
        properties = compute_air_properties(
            surface_temperature_c=inputs.surface_temperature_c,
            ambient_temperature_c=inputs.ambient_temperature_c,
        )
        warnings: list[str] = []
        if not AUTO_PROPERTY_MIN_TEMP_C <= properties.film_temperature_c <= AUTO_PROPERTY_MAX_TEMP_C:
            warnings.append(
                "Automatic air-property model is being used outside its preferred temperature range."
            )
        return properties, warnings

    if inputs.air_properties is None:
        raise ValueError("manual property mode requires AirProperties")

    _validate_air_properties(inputs.air_properties)
    return inputs.air_properties, []



def _reynolds_number(properties: AirProperties, velocity_m_per_s: float, characteristic_length_m: float) -> float:
    return properties.rho_kg_per_m3 * velocity_m_per_s * characteristic_length_m / properties.mu_pa_s



def _flat_plate_outcome(reynolds_number: float, prandtl_number: float) -> _CorrelationOutcome:
    warnings: list[str] = []
    if not 0.6 <= prandtl_number <= 60.0:
        warnings.append("Flat-plate correlation is outside its recommended Prandtl-number range.")

    if reynolds_number < 5.0e5:
        nusselt_number = 0.664 * reynolds_number**0.5 * prandtl_number ** (1.0 / 3.0)
        correlation_name = "Average laminar flat-plate correlation"
        regime_name = "laminar"
    else:
        nusselt_number = (0.037 * reynolds_number**0.8 - 871.0) * prandtl_number ** (1.0 / 3.0)
        correlation_name = "Average turbulent flat-plate correlation with leading-edge correction"
        regime_name = "turbulent / transitional"
        if reynolds_number > 1.0e7:
            warnings.append("Flat-plate turbulent correlation is being used beyond its preferred Reynolds-number range.")

    return _CorrelationOutcome(
        nusselt_number=nusselt_number,
        warnings=warnings,
        correlation_name=correlation_name,
        regime_name=regime_name,
    )



def _cylinder_crossflow_outcome(reynolds_number: float, prandtl_number: float) -> _CorrelationOutcome:
    warnings: list[str] = []
    if reynolds_number * prandtl_number <= 0.2:
        warnings.append("Churchill-Bernstein is outside its recommended Re·Pr applicability range.")

    numerator = 0.62 * reynolds_number**0.5 * prandtl_number ** (1.0 / 3.0)
    denominator = (1.0 + (0.4 / prandtl_number) ** (2.0 / 3.0)) ** 0.25
    correction = (1.0 + (reynolds_number / 282_000.0) ** (5.0 / 8.0)) ** (4.0 / 5.0)
    nusselt_number = 0.3 + numerator / denominator * correction

    return _CorrelationOutcome(
        nusselt_number=nusselt_number,
        warnings=warnings,
        correlation_name="Churchill-Bernstein cylinder crossflow correlation",
        regime_name="crossflow",
    )



def _sphere_crossflow_outcome(
    reynolds_number: float,
    prandtl_number: float,
    inputs: ConvectionInputs,
) -> _CorrelationOutcome:
    warnings: list[str] = []
    if not 3.5 <= reynolds_number <= 7.6e4:
        warnings.append("Whitaker sphere correlation is outside its recommended Reynolds-number range.")
    if not 0.71 <= prandtl_number <= 380.0:
        warnings.append("Whitaker sphere correlation is outside its recommended Prandtl-number range.")

    if inputs.auto_properties:
        mu_inf = _dynamic_viscosity_air_pa_s(inputs.ambient_temperature_c)
        mu_surface = _dynamic_viscosity_air_pa_s(inputs.surface_temperature_c)
        viscosity_ratio = mu_inf / mu_surface
    else:
        viscosity_ratio = 1.0
        warnings.append(
            "Manual property mode disables the free-stream / surface viscosity correction for the sphere correlation."
        )

    nusselt_number = (
        2.0
        + (0.4 * reynolds_number**0.5 + 0.06 * reynolds_number ** (2.0 / 3.0))
        * prandtl_number**0.4
        * viscosity_ratio**0.25
    )
    return _CorrelationOutcome(
        nusselt_number=nusselt_number,
        warnings=warnings,
        correlation_name="Whitaker sphere crossflow correlation",
        regime_name="crossflow",
    )



def _hausen_laminar_nusselt(reynolds_number: float, prandtl_number: float, diameter_m: float, length_m: float) -> float:
    graetz_number = reynolds_number * prandtl_number * diameter_m / length_m
    return 3.66 + (0.0668 * graetz_number) / (1.0 + 0.04 * graetz_number ** (2.0 / 3.0))



def _gnielinski_turbulent_nusselt(reynolds_number: float, prandtl_number: float) -> float:
    friction_factor = (0.79 * math.log(reynolds_number) - 1.64) ** -2
    numerator = (friction_factor / 8.0) * (reynolds_number - 1000.0) * prandtl_number
    denominator = 1.0 + 12.7 * (friction_factor / 8.0) ** 0.5 * (prandtl_number ** (2.0 / 3.0) - 1.0)
    return numerator / denominator



def _internal_tube_outcome(
    reynolds_number: float,
    prandtl_number: float,
    diameter_m: float,
    length_m: float,
) -> _CorrelationOutcome:
    warnings: list[str] = []
    laminar_nusselt = _hausen_laminar_nusselt(reynolds_number, prandtl_number, diameter_m, length_m)

    if reynolds_number < 2300.0:
        nusselt_number = laminar_nusselt
        correlation_name = "Hausen laminar internal-flow correlation"
        regime_name = "laminar"
    elif reynolds_number < 3000.0:
        turbulent_reference_nusselt = _gnielinski_turbulent_nusselt(3000.0, prandtl_number)
        transition_weight = (reynolds_number - 2300.0) / 700.0
        nusselt_number = (1.0 - transition_weight) * laminar_nusselt + transition_weight * turbulent_reference_nusselt
        correlation_name = "Transition interpolation between laminar Hausen and turbulent Gnielinski estimates"
        regime_name = "transition"
        warnings.append("Internal-flow result is in the transition range and should be treated as a low-confidence estimate.")
    else:
        nusselt_number = _gnielinski_turbulent_nusselt(reynolds_number, prandtl_number)
        correlation_name = "Gnielinski turbulent internal-flow correlation"
        regime_name = "turbulent"

    if regime_name != "laminar":
        if not 0.5 <= prandtl_number <= 2000.0:
            warnings.append("Gnielinski correlation is outside its recommended Prandtl-number range.")
        if not 3000.0 <= reynolds_number <= 5.0e6 and regime_name == "turbulent":
            warnings.append("Gnielinski correlation is outside its recommended Reynolds-number range.")
        if length_m / diameter_m < 10.0:
            warnings.append("Internal-flow turbulent estimate assumes a sufficiently long tube (L/D > 10).")

    return _CorrelationOutcome(
        nusselt_number=nusselt_number,
        warnings=warnings,
        correlation_name=correlation_name,
        regime_name=regime_name,
    )



def _correlation_outcome(
    inputs: ConvectionInputs,
    reynolds_number: float,
    prandtl_number: float,
) -> _CorrelationOutcome:
    if inputs.case == ConvectionCase.FLAT_PLATE:
        return _flat_plate_outcome(reynolds_number, prandtl_number)
    if inputs.case == ConvectionCase.CYLINDER_CROSSFLOW:
        return _cylinder_crossflow_outcome(reynolds_number, prandtl_number)
    if inputs.case == ConvectionCase.SPHERE_CROSSFLOW:
        return _sphere_crossflow_outcome(reynolds_number, prandtl_number, inputs)
    return _internal_tube_outcome(
        reynolds_number,
        prandtl_number,
        inputs.characteristic_length_m,
        inputs.flow_length_m,
    )



def _validate_inputs(inputs: ConvectionInputs) -> None:
    if inputs.velocity_m_per_s <= 0.0:
        raise ValueError("velocity must be positive")
    if inputs.characteristic_length_m <= 0.0:
        raise ValueError("characteristic length must be positive")
    if inputs.flow_length_m <= 0.0:
        raise ValueError("flow length must be positive")
    if inputs.area_m2 <= 0.0:
        raise ValueError("area must be positive")



def compute_case(inputs: ConvectionInputs) -> ConvectionResult:
    _validate_inputs(inputs)
    properties, property_warnings = _resolve_air_properties(inputs)
    reynolds_number = _reynolds_number(
        properties,
        inputs.velocity_m_per_s,
        inputs.characteristic_length_m,
    )
    prandtl_number = properties.prandtl_number
    outcome = _correlation_outcome(inputs, reynolds_number, prandtl_number)
    heat_transfer_coefficient = outcome.nusselt_number * properties.k_w_per_mk / inputs.characteristic_length_m
    heat_transfer_rate = heat_transfer_coefficient * inputs.area_m2 * (
        inputs.surface_temperature_c - inputs.ambient_temperature_c
    )
    return ConvectionResult(
        air_properties=properties,
        reynolds_number=reynolds_number,
        prandtl_number=prandtl_number,
        nusselt_number=outcome.nusselt_number,
        heat_transfer_coefficient_w_per_m2k=heat_transfer_coefficient,
        heat_transfer_rate_w=heat_transfer_rate,
        warnings=property_warnings + outcome.warnings,
        correlation_name=outcome.correlation_name,
        regime_name=outcome.regime_name,
    )



def generate_velocity_sweep(
    base_inputs: ConvectionInputs,
    v_min: float,
    v_max: float,
    points: int,
) -> VelocitySweepResult:
    if points <= 1:
        raise ValueError("points must be greater than 1")
    if v_min <= 0.0 or v_max <= 0.0:
        raise ValueError("velocity sweep limits must be positive")
    if v_max <= v_min:
        raise ValueError("v_max must be greater than v_min")

    step = (v_max - v_min) / (points - 1)
    velocities = [v_min + step * index for index in range(points)]
    heat_transfer_coefficients: list[float] = []
    heat_transfer_rates: list[float] = []
    for velocity in velocities:
        result = compute_case(base_inputs.with_velocity(velocity))
        heat_transfer_coefficients.append(result.heat_transfer_coefficient_w_per_m2k)
        heat_transfer_rates.append(result.heat_transfer_rate_w)

    return VelocitySweepResult(
        velocities_m_per_s=velocities,
        heat_transfer_coefficients_w_per_m2k=heat_transfer_coefficients,
        heat_transfer_rates_w=heat_transfer_rates,
    )


__all__ = [
    "AirProperties",
    "ConvectionCase",
    "ConvectionInputs",
    "ConvectionResult",
    "VelocitySweepResult",
    "compute_air_properties",
    "compute_case",
    "generate_velocity_sweep",
]
