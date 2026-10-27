## SERVOS

- `fuel_intake`: zawór dolotowy paliwa (0–100)
- `oxidizer_intake`: zawór dolotowy utleniacza (0–100)
- `fuel_valve`: główny zawór paliwa (0–100)
- `oxidizer_valve`: główny zawór utleniacza (0–100)

## RELAYS

- `oxidizer_heater`: przekaźnik grzałki / presuryzacji utleniacza (`True`/`False`)
- `igniter`: przekaźnik zapalnika silnika (`True`/`False`)
- `parachute`: przekaźnik mechanizmu spadochronu (`True`/`False`)

## SENSORS

- `fuel_level`: aktualny poziom paliwa w zbiorniku (%)
- `oxidizer_level`: aktualny poziom utleniacza w zbiorniku (%)
- `altitude`: aktualna wysokość rakiety nad ziemią (m)
- `oxidizer_pressure`: ciśnienie w zbiorniku utleniacza (bar)
- `nosecone_tilt`: kąt nachylenia głowicy rakiety (°)

## CHECKLIST AND LEDS

- `ox_filled`: status napełnienia zbiornika utleniacza do 100%
- `fuel_filled`: status napełnienia zbiornika paliwa do 100%
- `intakes_closed`: status zamknięcia obu zaworów dolotowych
- `ox_pressurized`: status osiągnięcia wymaganego ciśnienia utleniacza (57–59 bar)
- `ignition`: status gotowości / aktywacji zapalnika przy obecności paliwa i utleniacza
- `parachute`: status aktywacji spadochronu
- `status_preflight`: dioda fazy przedstartowej
- `status_burn`: dioda fazy zapłonu i ciągu
- `status_descend`: dioda fazy opadania

## AUTO STATE

- `pressurize_active`: flaga włączenia automatycznego regulatora ciśnienia utleniacza
- `last_heater_cmd_time`: znacznik czasu ostatnio wysłanej komendy do grzałki
- `last_ox_close_time`: znacznik czasu ostatniego automatycznego zamknięcia dolotu utleniacza
- `last_fuel_close_time`: znacznik czasu ostatniego automatycznego zamknięcia dolotu paliwa