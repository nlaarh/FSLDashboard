# Weather Analysis — AAA Roadside Service

## Module Location
- `apidev/weather.py` — Reusable WeatherAnalyzer class
- Open-Meteo API (free, no key, 10K requests/day)
- Historical: `archive-api.open-meteo.com/v1/archive`
- Forecast: `api.open-meteo.com/v1/forecast` (up to 16 days)

## Weather Stations (Western/Central NY)
| Station   | Lat   | Lon    |
|-----------|-------|--------|
| Buffalo   | 42.88 | -78.88 |
| Rochester | 43.16 | -77.61 |
| Syracuse  | 43.05 | -76.15 |
| Region Center | 43.01 | -77.65 |

## Key Findings (May-Dec 2025 = 338,254 SAs)

### Volume Drivers (ranked by impact)
1. **Day-of-Week (#1 driver)**: Mon 1,742/day → Sun 976/day (1.8x spread)
   - Weekday avg: 1,539 vs Weekend avg: 1,013 (1.5x)
2. **Seasonality (#2)**: Dec 1,635/day peak, May 914/day low (among tracked months)
3. **Cold Temperature (#3)**: Below 20°F → +27.9% vs avg (DOW-normalized)
   - Freezing temps → battery failures, tire deflation, engine issues
4. **Snow (#4, moderate)**: ≥1" snow → 1.15x multiplier (DOW-normalized)
   - Snow alone doesn't spike calls much; it's the cold that accompanies it

### Temperature Impact (DOW-normalized)
| Temp Range | Days | Avg (norm) | vs Avg |
|-----------|------|-----------|--------|
| Below 20°F | 14 | 1,780 | +27.9% |
| 20-32°F | 40 | 1,446 | +3.9% |
| 32-50°F | 68 | 1,209 | -13.1% |
| 50-70°F | 99 | 1,403 | +0.8% |
| 70-85°F | 99 | 1,403 | +0.8% |
| 85°F+ | 22 | 1,524 | +9.5% |

### Severity Classification Thresholds
- **Extreme**: ≥12" snow, ≥60mph wind, ≤-10°F, hail
- **Severe**: ≥6" snow, ≥2" rain, ≥45mph wind, ≤0°F
- **Moderate**: ≥2" snow, ≥0.5" rain, ≥30mph wind, ≤15°F or ≥95°F
- **Mild**: Any precip, ≥20mph wind, ≤25°F or ≥90°F
- **Clear**: Everything else

### Monthly Pattern (2025)
| Month | Avg/Day | Snow Days | Notes |
|-------|---------|-----------|-------|
| May | 914 | 0 | System ramp-up month |
| Jun | 1,487 | 0 | Summer surge starts |
| Jul | 1,505 | 0 | Peak summer |
| Aug | 1,421 | 0 | |
| Sep | 1,381 | 0 | |
| Oct | 1,378 | 0 | |
| Nov | 1,386 | 4 | First snow |
| Dec | 1,635 | 6 | Peak month — cold + holidays |

### Top Busiest Day Pattern
- 7 of top 10 busiest days = **Monday in December** with cold temps
- Dec 15 (Mon): 2,418 SAs — Heavy snowfall, 12-25°F
- Dec 8 (Mon): 2,346 SAs — Extreme cold 10°F
- Summer Mondays also high: Jul 7 (Mon): 2,175 SAs

## Data Quality Notes
- **Jan-Apr 2025 excluded**: Only ~90 SAs/day vs 1,000+ post-May (system not fully live)
- Use only May 2025+ data for weather correlation models
- 504K SAs have lat/lon coordinates (75.5%) for geographic analysis
- WorkType GROUP BY fails with aggregate query pagination limit

## Forecast-Based Driver Planning
- Model: severity_avg[weather] × dow_multiplier[day_of_week]
- Baseline: ~8 SAs per driver per shift (configurable)
- Forecast: 16-day window from Open-Meteo
- Flags: HIGH (>20% above avg), LOW (<20% below avg)
