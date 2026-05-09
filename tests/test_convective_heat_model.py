import math
import unittest

from convective_heat_model import (
    AirProperties,
    ConvectionCase,
    ConvectionInputs,
    compute_air_properties,
    compute_case,
    generate_velocity_sweep,
)


class AirPropertyTests(unittest.TestCase):
    def test_automatic_air_properties_are_physically_plausible(self) -> None:
        properties = compute_air_properties(
            surface_temperature_c=60.0,
            ambient_temperature_c=25.0,
        )

        self.assertAlmostEqual(properties.film_temperature_c, 42.5)
        self.assertTrue(1.0 < properties.rho_kg_per_m3 < 1.2)
        self.assertTrue(1.7e-5 < properties.mu_pa_s < 2.2e-5)
        self.assertTrue(0.026 < properties.k_w_per_mk < 0.030)
        self.assertTrue(990.0 < properties.cp_j_per_kgk < 1030.0)
        self.assertTrue(0.6 < properties.prandtl_number < 0.8)

    def test_manual_properties_are_preserved_exactly(self) -> None:
        manual = AirProperties(
            rho_kg_per_m3=1.08,
            mu_pa_s=1.95e-5,
            k_w_per_mk=0.028,
            cp_j_per_kgk=1009.0,
            film_temperature_c=50.0,
            source_label="manual override",
        )

        result = compute_case(
            ConvectionInputs(
                case=ConvectionCase.FLAT_PLATE,
                velocity_m_per_s=2.0,
                characteristic_length_m=0.5,
                flow_length_m=0.5,
                area_m2=1.0,
                surface_temperature_c=60.0,
                ambient_temperature_c=25.0,
                auto_properties=False,
                air_properties=manual,
            )
        )

        self.assertEqual(result.air_properties, manual)


class CorrelationTests(unittest.TestCase):
    def test_flat_plate_case_returns_reasonable_nominal_values(self) -> None:
        result = compute_case(
            ConvectionInputs(
                case=ConvectionCase.FLAT_PLATE,
                velocity_m_per_s=2.0,
                characteristic_length_m=0.5,
                flow_length_m=0.5,
                area_m2=1.0,
                surface_temperature_c=60.0,
                ambient_temperature_c=25.0,
            )
        )

        self.assertTrue(5.0e4 < result.reynolds_number < 7.5e4)
        self.assertTrue(120.0 < result.nusselt_number < 170.0)
        self.assertTrue(6.0 < result.heat_transfer_coefficient_w_per_m2k < 12.0)
        self.assertTrue(200.0 < result.heat_transfer_rate_w < 450.0)
        self.assertEqual(result.warnings, [])

    def test_cylinder_crossflow_case_returns_positive_transfer(self) -> None:
        result = compute_case(
            ConvectionInputs(
                case=ConvectionCase.CYLINDER_CROSSFLOW,
                velocity_m_per_s=5.0,
                characteristic_length_m=0.05,
                flow_length_m=0.05,
                area_m2=0.2,
                surface_temperature_c=80.0,
                ambient_temperature_c=25.0,
            )
        )

        self.assertTrue(result.reynolds_number > 1.0e4)
        self.assertTrue(result.nusselt_number > 20.0)
        self.assertTrue(result.heat_transfer_coefficient_w_per_m2k > 10.0)
        self.assertTrue(result.heat_transfer_rate_w > 0.0)

    def test_internal_tube_transition_case_emits_warning(self) -> None:
        result = compute_case(
            ConvectionInputs(
                case=ConvectionCase.INTERNAL_TUBE,
                velocity_m_per_s=2.4,
                characteristic_length_m=0.02,
                flow_length_m=0.4,
                area_m2=0.05,
                surface_temperature_c=80.0,
                ambient_temperature_c=25.0,
            )
        )

        self.assertTrue(any("transition" in warning.lower() for warning in result.warnings))

    def test_invalid_area_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            compute_case(
                ConvectionInputs(
                    case=ConvectionCase.SPHERE_CROSSFLOW,
                    velocity_m_per_s=3.0,
                    characteristic_length_m=0.1,
                    flow_length_m=0.1,
                    area_m2=0.0,
                    surface_temperature_c=70.0,
                    ambient_temperature_c=20.0,
                )
            )


class SweepTests(unittest.TestCase):
    def test_velocity_sweep_returns_finite_series(self) -> None:
        base_inputs = ConvectionInputs(
            case=ConvectionCase.FLAT_PLATE,
            velocity_m_per_s=2.0,
            characteristic_length_m=0.5,
            flow_length_m=0.5,
            area_m2=1.0,
            surface_temperature_c=60.0,
            ambient_temperature_c=25.0,
        )

        sweep = generate_velocity_sweep(base_inputs, v_min=0.1, v_max=10.0, points=25)

        self.assertEqual(len(sweep.velocities_m_per_s), 25)
        self.assertEqual(len(sweep.heat_transfer_coefficients_w_per_m2k), 25)
        self.assertEqual(len(sweep.heat_transfer_rates_w), 25)
        self.assertAlmostEqual(sweep.velocities_m_per_s[0], 0.1)
        self.assertAlmostEqual(sweep.velocities_m_per_s[-1], 10.0)
        self.assertTrue(all(math.isfinite(value) for value in sweep.heat_transfer_coefficients_w_per_m2k))
        self.assertTrue(all(math.isfinite(value) for value in sweep.heat_transfer_rates_w))


if __name__ == "__main__":
    unittest.main()
