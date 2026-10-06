# Wearable analytics: карта открытых реализаций

Дата проверки: **25 сентября 2026**. Это исследование исходников, а не проектирование новой аналитики. `health.sqlite`, ETL и production-окружение не изменялись. GitHub-ссылки на код закреплены за проверенным commit, поскольку формулы в этих проектах меняются. Числа stars/forks — снимок на дату проверки, не оценка качества. `A` означает стандартную статистическую/физиологическую процедуру, `B` — прозрачное авторское правило проекта, `C` — приближение к коммерческому продукту, чья исходная формула неизвестна. **Стандартная составляющая внутри score не делает весь score научно валидированным.**

## Executive summary

- Хорошо покрыты вычисления из **настоящих NN/RR/IBI или исходного PPG/ECG**: очистка интервалов, RMSSD, SDNN, pNN50, спектр, Poincaré. Есть независимые реализации в NOOP, GenieMax, OpenStrap, NeuroKit2, FLIRT, pyHRV и HeartPy. Из обычных периодических BPM настоящий beat-to-beat HRV восстановить нельзя.
- Для нагрузки доступны Banister/Edwards TRIMP, HR reserve, CTL/ATL/TSB, ACWR и несколько разных шкал strain. Сама математика нагрузки повторяется; перевод нагрузки в «WHOOP-подобные» 0–21 или 0–100, пороги и калибровка — решения проектов.
- Сон хорошо покрыт на уровне длительности, эффективности, стадий, WASO и временной регулярности. Готовые sleep scores, sleep need и debt **не эквивалентны**: проекты учитывают разные компоненты и по-разному обращаются с недостающими ночами. Настоящий Phillips SRI реализован в OpenStrap; одноимённый показатель GenieMax фактически является функцией разброса onset/wake.
- Recovery/readiness, resilience, health monitor, illness flags и привычки имеют несколько открытых реализаций, но универсальной доказанной формулы нет. Особенно важны разные правила при отсутствии HRV: Pulse допускает score от RHR, Vitals v3 требует HRV **или** сон, GenieMax и NOOP требуют HRV/baseline, OpenStrap требует минимум два компонента и достаточный общий вес.
- Для связи с Xiaomi всё ещё понадобится собственный слой соответствия метрик, единиц, локальных дат, качества сигнала, provenance и правил отсутствия данных. Это вывод о необходимой интеграции, **не выбор алгоритма**.

## Объекты и метод

Исследованы рабочие исходники и тесты, а не только README: NOOP (сохранившееся зеркало `ParthJadhav/noop`; название `noopwhoop` встречается у форков того же проекта), Vitals = `DocStream-Oficial/vitals`, GenieMax = `satayutata/geniemax-core`, Open Wearables = `the-momentum/open-wearables`, Pulse = `Luraxx/pulse`. `mstuart/vitals` и другие одноимённые репозитории — **другие** проекты и не подменяют здесь Vitals. Дополнительно изучены OpenStrap Analytics и пять signal-processing/sleep библиотек. Локальные research-копии находятся в `/Users/rus/Documents/temp/wearable_research/`; ничего оттуда не установлено в production.

Для “last meaningful commit” использовано изменение функций/поведения, найденное в истории, а не слепо `pushed_at`: push может быть README, релизом или обновлением зависимостей. Для больших проектов дата характеризует проект в целом, не каждый отдельный алгоритм. Ссылки на функции ниже дают проверяемую версию каждой формулы.

## Project profiles

| Проект и GitHub | Язык; активность и содержательный commit | Stars / forks | Лицензия и статус | Зависимости; отделимость analytics |
|---|---|---:|---|---|
| [NOOP mirror](https://github.com/ParthJadhav/noop) (`63f3ed0`) | Swift и Kotlin; зеркало обновлено 08.07.2026; 23.06.2026 — большой релиз с переработкой sleep, в текущем дереве также тесты и модули аналитики | 94 / 81 | [PolyForm Noncommercial 1.0.0][N-license]; source-available. Личный некоммерческий запуск/модификация разрешены; коммерческое использование кода не предоставлено | SwiftPM [`StrandAnalytics`][N-package] — довольно отделённый вычислительный модуль, но использует `WhoopStore`/модели; Android имеет Kotlin twin. BLE/UI не нужны для изучения формул, адаптер типов нужен для переноса. В полном приложении GRDB/ZIPFoundation и платформенные зависимости. Это snapshot зеркала, а не заявление о текущем head исходного NOOP. |
| [Vitals](https://github.com/DocStream-Oficial/vitals) (`fb3a837`) | Python (+ Swift iOS); 08.08.2026 — исправление классификации nap и агрегирования сна | 3 / 0 | [MIT][V-license]; OSS, личное и коммерческое использование кода с сохранением notice | Pure Python `app/load.py`, `sleep_scores.py`, `trends.py`, `scoring.py` почти отделяются; полное приложение требует FastAPI, Uvicorn, APScheduler, requests, OAuth/провайдеров. `build_dataset` сильнее связан с собственной моделью данных. |
| [GenieMax Core](https://github.com/satayutata/geniemax-core) (`4765501`) | Swift; последняя содержательная публикация ядра 21.06.2026; последующие commits в основном документация | 138 / 53 | [MIT][G-license]; OSS, личное и коммерческое использование с notice | SwiftPM `Sources/GenieMax` — отдельный engine и golden fixtures. Весь package зависит от swift-sodium/libsodium ради vault, хотя многие математические файлы не используют crypto; перенос отдельных алгоритмов технически возможен после выделения типов. |
| [Open Wearables](https://github.com/the-momentum/open-wearables) (`fd78bdd`) | Python/TypeScript; 24–25.09.2026 есть функциональные и dependency commits | 2562 / 496 | [MIT][O-license]; OSS, личное и коммерческое использование с notice | `backend/app/algorithms` отделяет pure функции (`pydantic`, `numpy`); score services зависят от SQLAlchemy/Postgres, API и своих моделей. Можно отдельно изучать pure functions; DB-backed сервис переносится с адаптером. |
| [Pulse](https://github.com/Luraxx/pulse) (`1f8975c`) | Swift; 01.08.2026 исправлена логика sleep debt/калибровки | 28 / 2 | [Apache-2.0][P-license]; OSS, личное и коммерческое использование с NOTICE/патентными условиями | `Core/Metrics` в самостоятельном `PulseCore` SwiftPM; UI, Google Health API и локальное хранилище отделены. Алгоритмы можно изучать/подключать без iOS UI, адаптер `DayRecord` потребуется. |
| [OpenStrap Analytics](https://github.com/OpenStrap/analytics) (`0441ef9`) | Dart; 19–22.09.2026 менялись guards для baseline, sleep window и readiness | 10 / 18 | [MIT][S-license]; OSS, личное и коммерческое использование с notice | Pure Dart, **нет runtime-зависимостей**, `Metric<T>` возвращает value/confidence/tier/причину отказа. Dev tests используют `test` и protocol fixture. Большинство алгоритмов автономны, но их надо переписывать/запускать через Dart для Python/Mac стека. |
| [NeuroKit2](https://github.com/neuropsychology/NeuroKit) (`ff419d9`) | Python; код и CI поддерживаются в 2026 (например fix 24.02.2026; недавние commits релизной инфраструктуры) | 2366 / 544 | [MIT](https://github.com/neuropsychology/NeuroKit/blob/ff419d983568ef492eb8d229af643c0ef0100b32/LICENSE); OSS | NumPy, SciPy, pandas, matplotlib и др.; функции HRV/ECG/PPG/RSP отделены от UI, но не от научного Python стека. Проверен [исходник `hrv_time`][K-hrv] и [frequency][K-freq] через официальный raw repository; полный clone в этой исследовательской сессии не завершился. |
| [FLIRT](https://github.com/im-ethz/flirt) (`d9bdcc5`) | Python; последняя кодовая правка 06.11.2023 | 84 / 24 | [MIT c отдельной оговоркой GPL-3.0 для cvxEDA][F-license]; OSS с компонентным исключением | NumPy, pandas, SciPy, numba, astropy и др.; HRV sliding-window features отдельно от EDA/ACC. Не считать весь импорт пакета автоматически MIT, если затрагивается cvxEDA. |
| [pyHRV](https://github.com/PGomes92/pyhrv) (`e90219c`) | Python; релиз/упаковка 17.06.2026, основные функции старше | 341 / 88 | [BSD-3-Clause][Y-license]; OSS, коммерческое использование с notices | BioSPPy, NumPy, SciPy, matplotlib, nolds, spectrum; модули `time_domain`, `frequency_domain`, `nonlinear` отдельно, но с общими utils. |
| [HeartPy](https://github.com/paulvangentcom/heartrate_analysis_python) (`ef48d23`) | Python; поддержка 30.12.2025 в основном packaging/docs; алгоритмы старше | 1143 / 347 | [MIT][H-license]; OSS | NumPy, SciPy, matplotlib. Пульсовые пики/IBI и HRV features отделимы от графиков, но проверка качества исходного PPG остаётся обязательной. |
| [OxWearables asleep](https://github.com/OxWearables/asleep) (`79a9f65`) | Python/PyTorch/Java; 06.03.2026 — Apple Silicon MPS/offline models | 55 / 16 | **[Academic Use Licence][A-license], source-available**, не OSI OSS. Текст разрешает только внутренние академические некоммерческие исследования; обычное личное consumer-использование и коммерческая интеграция не разрешены без отдельной лицензии | `torch`, `actipy`, `stepcount`, pandas, SciPy, Java; модель/веса и полная акселерометрия. Архитектура классификатора отделима, но license и тяжёлый runtime ограничивают перенос. **`pyproject.toml` ошибочно содержит classifier “MIT”; текст LICENSE.md имеет приоритет.** |

Активность и stars/forks получены из публичных GitHub metadata и [commit history](https://docs.github.com/en/rest/commits/commits), 25.09.2026. Краткий статус тестов: NOOP — Swift/Kotlin unit tests и межплатформенные parity checks; Vitals — `tests/test_engine_v3.py`, `test_sleep_scores.py`, `test_load.py`/regression fixtures; GenieMax — `Tests/GenieMaxTests/Fixtures/*_golden.json` и replay parity; Open Wearables — score unit/integration tests; Pulse — executable `SelfTest` (проверить покрытие при переносе); OpenStrap — много unit tests и fixture реальной ночи; NeuroKit2/FLIRT/pyHRV/HeartPy/asleep — научные/пакетные тесты разной полноты. Наличие тестов **не означает** клинической валидации score.

## Algorithm catalog

Сокращения: `NN` = очищенные normal-to-normal интервалы, `RR` = beat-to-beat интервалы, `RHR` = resting heart rate, `RRsp` = respiratory rate, `TST` = total sleep time, `WASO` = wake after sleep onset, `SWC` = smallest worthwhile change, `∅` = нет результата. `~` обозначает ориентировочную длительность, а не скрытое заполнение дыр. Окна «N чтений» отличаются от N календарных дней. Ниже перечислены вычислительные семейства с разными inputs/правилами пропусков; однотипные математические варианты внутри семейства перечислены вместе.

### Heart, HRV и baseline

| Project | Metric [тип] | Algorithm / constants | Inputs | Window | Output | Missing-data behavior | Source file/function | License |
|---|---|---|---|---|---|---|---|---|
| NOOP | ночной RHR [A+B] | минимум средних 5-мин бинов; кандидат ≥5 samples и ≥25 bpm | HR samples с timestamp, sleep start/end | текущая ночь, bins 5 min | bpm | нет HR → ∅; если нет qualified bins, минимум всех bin means или overall mean | [RecoveryScorer.restingHR][N-rec] | PolyForm NC |
| NOOP | RMSSD, SDNN [A] | range filter, ectopic rejection; successive NN differences / SD | реальные RR/IBI с timestamp | заданное beat окно; rolling вариант | ms + quality | малое/испорченное окно → ∅, rejected fraction сообщается | [HrvAnalyzer.analyze][N-hrv] | PolyForm NC |
| NOOP | HRV frequency [A] | спектральные LF/HF и др. из RR | реальные интервалы + время | beat окно | power / ratio | нет RR/достаточной длины → ∅ | [HRVFreqDomain][N-freq] | PolyForm NC |
| NOOP | персональные EWMA baselines [A+B] | среднее/разброс, half-life, seed/status (`calibrating`, `trusted`, `stale`) | история HRV/RHR/RRsp/temp по ночам, metric config | последовательность ночей; recovery seed и freshness rules | baseline, spread, status, z | вне диапазона пропускается; без seed нет usable baseline | [Baselines.update/deviation][N-base] | PolyForm NC |
| GenieMax | HRV time domain [A] | RMSSD, population SDNN, SD1≈RMSSD/√2, SD2, Baevsky SI (50 ms bins) | **RR ms** | одно окно, ≥3 RR; SI ≥20 | ms / stress index | меньше порога или нулевая вариация для SI → ∅ | [HRV.metrics/baevskySI][G-hrv] | MIT |
| GenieMax | rolling baseline [A+B] | EWMA mean/variance; α=.25 HRV, .0645 RHR/RRsp/sleep/temp, ready ≥7 | nightly lnRMSSD, RHR, RRsp, sleep score, temp | ≥7 наблюдений | z + readiness flag | до 7 или sd=0 → z=∅ | [RollingBaseline][G-base] | MIT |
| Pulse | baseline / trend [A+B] | mean + sample SD, z, logistic; moving average / weekly mean | одноимённые daily series с датой | 30 значений для recovery; ≥3 для baseline, reliable ≥5 | mean, SD, z, trend | <3 → baseline=∅; <5 score может быть, но `calibrating` | [Stats.baseline/TrendMath][P-stats] | Apache-2.0 |
| Vitals | recent baseline / variability [A+B] | EWMA α=2/31 для HRV/RHR; rolling population SD; fallback all-time | датированные HRV/RHR и др. | 30 последних **чтений**, min 5 | mean/SD | недостаточно → `None`; `recent_base` может взять all-time | [scoring._ewma_recent/_rolling_sd][V-score] | MIT |
| Open Wearables | overnight HRV-CV [A+B] | CV = sample SD / mean дневных средних RMSSD; score 100 при CV≤7%, 0 при ≥40% | **измеренный RMSSD**, sleep stage windows | 7 прошлых UTC-дней, ≥5 дней | CV + 0–100 resilience | нет sleep-window RMSSD/5 дней → `null`; текущий код **отключает** SDNN fallback | [ResilienceScoreService.get_hrv_cv_score][O-res-svc] | MIT |
| Open Wearables | «RMSSD_OW/SDNN_OW» из BPM [B; **не валидный HRV**] | `60000/BPM` для каждой HR-точки, затем разности/std | периодические BPM, sleep stages | sleep window, min 20 точек | число с именем RMSSD/SDNN | <20 → `None`; **обычный BPM не задаёт каждый RR interval**, поэтому нельзя использовать как настоящий HRV | [resilience.calculate_rmssd/sdnn][O-res] и [service][O-res-svc] | MIT |
| OpenStrap | RR correction + HRV [A] | Lipponen–Tarvainen artifact correction; RMSSD/SDNN/pNNx/Poincaré, ночные 5-min segments | raw RR, beat timestamps, artifact fraction | beat window / ночные 5-min окна | `Metric<T>` + confidence | порог качества/покрытия не пройден → `value=null`, reason | [correctRr][S-rr], [hrvTime][S-hrv] | MIT |
| OpenStrap | lnRMSSD readiness [A+B] | среднее/SD предшествующих ночей, CV, SWC=.5 SD, ±SWC band | ночной lnRMSSD, optional mean NN | 7 предшествующих ночей, min 4 total | z, CV, band, saturation flag | мало ночей/неопределённый SD → absent; текущая ночь исключена из baseline | [readinessLnRmssd][S-ln] | MIT |
| NeuroKit2 | HRV time/frequency [A] | SDNN, RMSSD, pNN50/20, CVNN, Welch/Lomb и др. | R-peaks или настоящие RRI + sampling rate/timestamps | анализируемый signal segment; некоторые indices требуют ≥3/6/15 min | DataFrame признаков | короткие сегменты для SDANN/SDNNI дают NaN/пропуск; gap mask для последовательных RR | [hrv_time][K-hrv], [hrv_frequency][K-freq] | MIT |
| FLIRT | wearable HRV features [A] | time/frequency/nonlinear features по NN в sliding windows | датированные NN intervals; optional clean_data | по умолчанию 180 s, step 1 s | DataFrame features | окно без достаточных NN → NaN/пустые признаки, не recovery score | [get_hrv_features][F-hrv] | MIT; cvxEDA отдельно GPL |
| pyHRV | HRV battery [A] | SDNN/RMSSD/pNN50; FFT/Welch/Lomb/AR; Poincaré/DFA | NN intervals или R-peaks | поданное окно; отдельные функции сегментируют по 300 s | feature dictionary | нет NN/R-peaks → исключение/пустой результат зависит от функции, не единый nullable contract | [time_domain][Y-time], [frequency_domain][Y-freq], [nonlinear][Y-nl] | BSD-3-Clause |
| HeartPy | PPG/ECG peak + HRV features [A] | peak detection/cleaning, IBI, RMSSD/SDNN/pNN50, spectral/Poincaré | raw PPG/ECG + sample rate | signal segment | feature dict | плохие пики/недостаток RR → предупреждения/ошибки/NaN, зависит от функции | [calc_rr/calc_ts_measures][H-analysis] | MIT |

### Recovery, readiness, wellness и отклонения

| Project | Metric [тип] | Algorithm / constants | Inputs | Window | Output | Missing-data behavior | Source file/function | License |
|---|---|---|---|---|---|---|---|---|
| NOOP | Recovery/Charge [C] | robust z по EWMA; веса HRV .55, RHR .20, RRsp .05, sleep/Rest .15, temp .05; logistic k=1.6, z0=−.20 | ночной **RMSSD**, RHR, RRsp, Rest score, skin-temp deviation и baselines | текущая ночь vs предшествующие EWMA | 0–100 + band | нет usable HRV baseline → ∅; optional terms исключаются и веса перенормируются | [RecoveryScorer.recovery][N-rec] | PolyForm NC |
| Vitals | Recovery v3 **активная ветка** [B/C] | HRV .55, RHR .25, sleep .20; rolling mean/SD, z, logistic `100/(1+exp(-(1.06+.85·W)))`; SD floors 3 ms/1.5 bpm | HRV ms, RHR bpm, asleep min, configurable NEED | trailing 90 календарных дней, последние 30 чтений; текущий день включён | 0–100 + `recovery_n` | отсутствующий term исключён/weights normalized; score лишь при HRV **или** asleep; RHR-only → ∅ | [`RECOVERY_ANCHORED=True`, `build_dataset`][V-score] | MIT |
| Vitals | Recovery v2 **неактивная ветка** [B/C] | percentile 5/95, те же веса | HRV, RHR, asleep/NEED | 90 d ≥30 readings; 10–29 all-history; <10 fixed ranges | 0–100 | excludes missing terms; single-term exact 0/100 suppressed | [_rolling_percentile_ranges/build_dataset][V-score] | MIT |
| Pulse | Recovery [B/C] | HRV .40, RHR .25, sleep performance .25, RRsp .10; z/logistic; SpO₂min<90: −7, temp z>1.8: −5 | RMSSD, RHR, sleep performance, RRsp, SpO₂min, temp + histories | текущий день vs до 30 последних значений | 1–99, band | **RHR или HRV обязательны**; без HRV, но с RHR score есть; optional terms reweighted; baseline <3 даёт neutral fallback (.5 HRV/RHR, .65 RRsp), calibrating flag | [RecoveryEngine.compute][P-rec] | Apache-2.0 |
| GenieMax | Recovery [B/C] | `100·Φ(.55zHRV−.20zRHR−.10zRRsp+.15zSleep)` | ночные RMSSD (log), RHR, optional RRsp/sleep score + prior EWMA | ночь; baseline ≥7 | 0–100 или ∅ | **HRV и RHR/both baselines обязательны**; RRsp/sleep missing → neutral z=0; до warmup → ∅ | [RecoveryEngine.process][G-rec], [Scores.recovery][G-scores] | MIT |
| GenieMax | Readiness [B] | `.5 recovery + .3 sleepScore + .2 TSBnorm − illnessPenalty` | recovery, sleep score, TSB norm, penalty | текущий день / TSB history | 0–100 | вызов `RecoveryEngine` использует `sleepScore ?? recovery`, `TSBnorm=50`; без recovery → ∅ | [Scores.readiness][G-scores], [RecoveryEngine.process][G-rec] | MIT |
| GenieMax | resilience [B/C] | `.6 meanRecovery + .4 meanSleep − 30·CV(recovery)` | nightly recovery/sleep scores | 14 последних дней, min 5 recovery | 0–100 + level | без 5 recovery → ∅; без sleep meanSleep=meanRecovery | [DailyMetricsEngine.resilience][G-daily] | MIT |
| Open Wearables | resilience [B] | overnight RMSSD CV, linear mapping 7–40% → 100–0 | измеренный RMSSD внутри сна | 7 d, 5 valid | 0–100 или null | **без HRV весь score null**; SDNN fallback в коде отключён | [service.get_hrv_cv_score][O-res-svc] | MIT |
| OpenStrap | canonical readiness [B/C] | robust median/MAD z, mean/SD fallback; weighted oriented z; logistic 0–100; outlier/quantization guards | nightly HRV, RHR, RRsp, temp и **каждый** личный baseline | ≥14 prior nights per usable input | score, drivers, confidence/refusals | ≥2 inputs и sum weights≥.5; остальное ∅ с причиной; present weights normalized | [readinessComposite][S-ready] | MIT |
| OpenStrap | percentile glassbox **deprecated** [B] | per-input personal percentile, weighted mean, signed drivers | HRV/RHR/RRsp/temp + individual history | per-input history | 0–100/narrative | reweight missing; **не canonical headline** по source comment | [glassBoxReadiness][S-glass] | MIT |
| NOOP | readiness signals [B/C] | HRV/RHR/RRsp z; ACWR, weekly monotony; categorical synthesis | сегодняшние HRV/RHR/RRsp/strain и предыдущие days | 30-day baseline min 7; acute 7/chronic 28, min 14 | `primed/balanced/strained/rundown/insufficient`, drivers | отсутствующий signal опущен; при explicit today без row → insufficient | [ReadinessEngine.evaluate][N-ready] | PolyForm NC |
| Pulse | health baseline bands [B] | mean ±max(1.65 SD, sensor minimum width); alert streak | RHR, HRV, RRsp, SpO₂, temp | 30 прошлых значений; reliable ≥5 | in/out band, alert | нет значения→`noData`; мало history→`calibrating`; no imputation | [HealthMonitor.evaluate/alert][P-monitor] | Apache-2.0 |
| NOOP | multi-signal illness heads-up [B] | threshold z≥2, ≥2 signals, score per signal cap40; confounder factor .45 | RHR↑, temp↑, HRV↓, RRsp↑ z; journal alcohol/stress/sauna/workout/travel | текущая ночь vs trusted baseline ≥14 nights | 0–100, mild/raised/suppressed | нет trusted baseline или corroboration → quiet; missing signal ignored | [IllnessSignalEngine.evaluate][N-ill] | PolyForm NC |
| GenieMax | CUSUM alerts [A+B] | standardized positive/negative CUSUM k=.5,h=5; combined alert rules | nightly RHR, lnRMSSD, temp, RRsp, TSB/strain | accumulated daily series; last alarm | hi/lo alerts | sd≤0/empty → no alarm; quality gates in alert rules | [DailyMetricsEngine.cusumState/evaluateAlerts][G-daily] | MIT |
| Vitals | wellbeing [B] | HRV .30, RHR .25, RRsp .15, SpO₂ .15, skin temp .15; z/threshold sub-scores | daily HRV/RHR/RRsp/SpO₂/temp + recent baselines/SD | 30 readings baseline | 0–100 | unavailable terms dropped and weights normalized; zero terms→`None`; SD floors | [compute_wellbeing][V-score] | MIT |
| Vitals | illness early warning [B] | z deviations, corroborating signals and thresholds | RHR, HRV, RRsp, temp, SpO₂ + history/summary | recent vs baseline | watch/alert rule | insufficient baseline/signals → no insight | [rule_illness_early_warning][V-insights] | MIT |
| OpenStrap | CUSUM / multivariate anomaly [A+B] | change-point CUSUM; robust covariance/Mahalanobis-style deviation | RHR, HRV, RRsp/temp nightly series | min 7 baseline CUSUM / min 10 anomaly | event series + confidence | not enough baseline→no flagged result/absent; robust quantization guards | [illnessCusum][S-cusum], [multivariateAnomaly][S-anomaly] | MIT |
| Pulse | Pulse Age [B/C] | age from VO₂max norm .7 + HRV norm .3, capped RHR/sleep/steps offsets | VO₂max (or estimated), HRV, RHR, sleep performance, steps, age/sex | 14 provisional / ~30 calibration days | age estimate + components | without VO₂max backbone or <14 days → age ∅; optional metrics drop terms | [AgeEngine.compute][P-age] | Apache-2.0 |
| Vitals | body age/healthspan [B/C] | non-exercise VO₂ regression + HRV/sleep penalties; trend of age gap | age, sex, waist, RHR, workout frequency/intensity/duration, HRV, sleep | workout 28 d; HRV/sleep 14 d; healthspan ≥120 d, 90-d slices | VO₂/fitness age/body age/pace | missing RHR fallback 55; missing HRV/sleep omits penalty; insufficient healthspan → `None` | [compute_body_age][V-age], [compute_healthspan][V-span] | MIT |

### Activity, training load и sleep

| Project | Metric [тип] | Algorithm / constants | Inputs | Window | Output | Missing-data behavior | Source file/function | License |
|---|---|---|---|---|---|---|---|---|
| NOOP | HRmax/HRR/Edwards TRIMP [A+B] | Tanaka `208−.7·age`; observed p99.5 if ≥600 samples; HRR zones 50–90% with weights 1–5 | HR samples+times, RHR, age/sex | day/workout | TRIMP | HRmax unknown/invalid → ∅; HR stream <600 samples **and** <10 min span → strain ∅; RHR default 60 | [StrainScorer][N-strain] | PolyForm NC |
| NOOP | Banister TRIMP [A] | per-sample `duration·HRR·.64·exp(b·HRR)`, b=1.92 male/1.67 female | HR samples/times, RHR, HRmax, sex | day/workout | load | same coverage/HRR gates | [banisterTRIMP][N-strain] | PolyForm NC |
| NOOP | Effort strain [C] | `100·ln(TRIMP+1)/ln(7201)` in current Swift; tunable denominator | TRIMP | day/workout | **0–100**, not 0–21 | no trustworthy HR coverage → ∅ | [trimpToStrain][N-strain] | PolyForm NC |
| Vitals | Banister TRIMP [A] | `dur·HRR·(.64e^1.92HRR M / .86e^1.67HRR F)`; HRmax `211−.64age` | session duration, avg HR, RHR, age, sex | session | load | required input absent or invalid reserve→`None`; HR≤RHR→0 | [trimp_session][V-load] | MIT |
| Vitals | strain v2 [B/C] | `L=TRIMP` else `2.5·vigorousMinutes`, plus `steps/500`; `21(1−e^(−L/96.87))` | TRIMP/day, vigorous min, steps | day | 0–21 | none of three signals→`None`; HR missing permits steps/vigorous fallback | [_strain_v2][V-score] | MIT |
| Pulse | HRR zone strain [B/C] | zones HRR .20/.30/.45/.60/.72/.85, weights .5/1/2.5/5/8/11; `21(1−e^(−raw/450))` | HR samples/times, RHR (fallback 62), HRmax override or Tanaka, workout avg HR/duration, steps | day or workout | 0–21, zone minutes | no intraday HR → workout/steps proxy; no signals→0; workout without HR→`nil` | [StrainEngine][P-strain] | Apache-2.0 |
| GenieMax | strain + CTL/ATL/TSB [A+B/C] | `21(1−e^(−TRIMP/τ))`, default τ100; EWMA τ42/7, TSB=CTL−ATL; ACWR 7/28 means | HR-derived TRIMP, chronological daily loads | current day + whole history | 0–21, fitness/fatigue/form/ACWR | `performanceModel` seeds zero and treats supplied zeros as rest; `acwr` only checks chronic≠0; caller must mark missing days separately | [Scores.strain/performanceModel/acwr][G-scores] | MIT |
| Vitals | ACWR [A+B] | sum last 7 / (sum last 28 / 4); categories <.8, ≤1.3, ≤1.5, >1.5 | daily strain series with `None` vs 0 distinguished | up to 28 d, ≥14 real days | ratio/category | chronic≤0 or <14 data days→`None` | [acwr/acwr_zone][V-load] | MIT |
| OpenStrap | TRIMP/strain + CTL/ATL/TSB [A+B/C] | Banister from actual HR/RHR/HRmax; 0–100 log strain; EWMA τ42/7, first 7-day mean seed | beat/HR stream, RHR, HRmax; daily TRIMP | session/day; ≥14 load days | load, score, fitness/fatigue/form | insufficient HR/14 days→`Metric.absent` + reason; missing daily load represented as 0 only if caller passes 0 | [banisterTrimp/ctlAtlTsb][S-load] | MIT |
| OpenStrap | overreaching conjunction [B] | load/HRV/RHR conjunction rather than ACWR-only alarm | daily TRIMP, HRV, RHR + baselines | recent vs ≥14 baseline | flagged / no flag | missing corroboration/baseline→absent | [overreachingConjunction][S-over] | MIT |
| NOOP | Rest sleep score [B/C] | duration .50, efficiency .20, deep+REM restorative .20, consistency .10; deep adequacy factor ≥.13 | TST, in-bed, efficiency, deep/REM seconds, need, regularity | night + optional schedule history | 0–100 | `DailyMetric` path requires TST and efficiency; missing consistency=.5; missing stage totals currently 0 | [AnalyticsEngine.Rest.composite][N-ana] | PolyForm NC |
| Open Wearables | sleep score [B] | duration .40 (7–9h), deep+REM .20 (90 min each), bedtime median consistency .20, interruptions .20 | net TST, deep min, REM min, bedtime+history, WASO+awakening durations | night + previous 14 bedtimes in service | 0–100 + pillars | TST≤0 or >24h→error; no history→consistency=0, missing stages passed as 0→stage=0; no stage WASO falls back to awake minutes | [calculate_overall_sleep_score][O-sleep], [SleepScoreService][O-sleep-svc] | MIT |
| GenieMax | sleep score [B/C] | `.55·min(TST/8h,1)+.25·eff+.20·min((deep+REM)/(.4TST),1)` | epoch stages/TST, time in bed | current night | 0–100 | failed main sleep block→no sleep result; score has hard-coded 8h need; regularity/latency excluded | [SleepStaging.stage][G-stage] | MIT |
| Vitals | sleep performance/need/debt [B] | performance=TST/target; need=target+min(.3·7d deficits,60)+20 if strain>14+20 if recovery<34 | asleep, user target (default 480 min), 7d sleep, today strain/recovery | night / 7 d | 0–100, need min | missing asleep/need→score `None`; missing strain/recovery=no corresponding extra; **debt sums deficits only**, surplus never repays | [sleep_score/sleep_need_min][V-sleep] | MIT |
| Pulse | sleep need/debt/performance [B/C] | base 456 min + .30 debt + previous strain boost max45; debt cap300, nightly gain cap180, surplus repays | all sleep sessions incl naps, main sleep, prior-day strain | chronological days + 4 bedtime/wake pairs | need/debt/0–100 performance | no main sleep→performance **0**, debt unchanged; missing strain→0 boost; missing stage split→all light | [SleepEngine.analyze][P-sleep] | Apache-2.0 |
| NOOP | sleep debt ledger [B] | sum(TST−need) over last 14 **usable nights**, surplus offsets deficits | TST per night, personal need default 8h | 14 counted nights | signed balance + per-night delta | missing/nonpositive night skipped, empty ledger balance 0 with no nights | [SleepDebt.ledger][N-debt] | PolyForm NC |
| GenieMax | sleep need/debt [B/C] | need=base+(strain/21)·.75h+min(.3·debt,1.5h); debt=sum max(0,8−TST) | daily strain, TST/stage durations | today / last 7 days | h need, h debt | missing stage fields become 0 TST in debt calculation; risk of artificial debt | [Scores.sleepNeedH][G-scores], [DailyMetricsEngine.sleepDebt][G-daily] | MIT |
| OpenStrap | sleep need/debt proxy [B] | p75 of unconstrained-night duration minus median recent; **не измеренная physiological need** | recent sleep lengths, free-night lengths/alarm context | ≥3 recent + available free nights | habitual, p75, gap | no free nights → gap null with note; no 3 recent → absent | [sleepDebt][S-debt] | MIT |
| Vitals | sleep consistency [B] | mean of SD(bedtime) and SD(wake); 100 at ≤20 min, 0 at ≥120 | bed_min, wake HH:MM | last 14 nights, ≥5 complete | 0–100 | <5 complete → `None` | [consistency_score][V-sleep] | MIT |
| Pulse | sleep consistency [B] | circular deviation of bed+wake from previous up to 4 nights; 100−meanDev/90·100 | main sleep start/end local clock | current + 4 nights | 0–100 | no earlier pair→`nil` | [SleepEngine.analyze][P-sleep] | Apache-2.0 |
| GenieMax | «SRI» proxy [B] | mean SD of shifted onset/wake; `100(1−SD/120)` | onset/wake minutes | last 7 nights, ≥3 each | 0–100 | short history→`nil`; **это не Phillips epoch SRI** | [DailyMetricsEngine.sri][G-daily] | MIT |
| OpenStrap | Phillips SRI [A] | `200·same-state clock epoch pairs / valid pairs −100` | clock-aligned sleep/wake epoch booleans + valid mask | ≥2 full 24h days | SRI −100…100 + pair counts | no valid pairs/short days→absent; thin pairs excluded from pair list, но общий score использует все валидные pairs — проверить при переносе | [phillipsSri][S-sri] | MIT |
| OpenStrap | sleep window/nap/stages [A+B] | van Hees angle; motion/cardiac stage rules; nap detector | high-frequency wrist acceleration, HR, RR/resp | multi-hour sleep window | session/stages/nap | insufficient raw sensor coverage→`Metric.absent`; нет полного потока → не применимо к готовым Xiaomi sleep stages | [vanHeesSleepWindow][S-van], [detectNaps][S-nap] | MIT |
| GenieMax | sleep staging/nap [A+B] | Cole–Kripke activity + HR/HRV refinement; 60s epochs; gaps <10min merge | motion/HR/HRV/resp samples with timestamps | ночь, ≥1h main block | sleep/wake/deep/light/REM, nap flag | no main block → `ok=false`; daytime 10–20h midpoint + <4h => napLikely | [SleepStaging.stage][G-stage] | MIT |
| asleep | sleep stage ML [A: исследовательская модель] | trained accel CNN/LSTM classifier + sleep windows, TST, efficiency, REM/NREM | raw tri-axial acceleration with timestamps/sampling rate + model weights | 30s epochs, recording across nights | wake/NREM/REM + summaries | без raw acceleration/весов модель неприменима; pipeline may download weights unless preloaded; license academic-only | [sslmodel.predict][A-model], [sleep_stats][A-stats] | Academic Use |

### Тренды, корреляции и прочие полезные механизмы

| Project | Metric [тип] | Algorithm / constants | Inputs | Window | Output | Missing-data behavior | Source file/function | License |
|---|---|---|---|---|---|---|---|---|
| NOOP | correlation / lag [A+B] | Pearson r, OLS slope/intercept; approximate p via **normal**, не точный Student-t | две числовые daily series + day keys | совпавшие дни; заданный lag | r,n,pApprox,slope | <3 pairs/zero variance → ∅; duplicate day last-write | [CorrelationEngine.pearson/lagged][N-corr] | PolyForm NC |
| NOOP | habit effect [A+B] | lagged effect, Cohen's d/Welch approximation and confidence | journal tags + daily outcome series | lagged day pairs | ranked associations | too few pairs / incomplete history → confidence reduced/no result | [EffectRanker.rank][N-effect] | PolyForm NC |
| Vitals | trend [A] | OLS, Theil–Sen slope, Mann–Kendall | ordered daily numeric observations | caller's series | slope/trend/p | short/invalid series→`None` | [trends.py][V-trends] | MIT |
| OpenStrap | associations [A+B] | calendar-grid alignment, lag, weekday adjustment, rank correlation, 14-day block permutations, FDR, contrast/coverage gates | daily metric + journal series, measured mask, dates | ≥84 paired days, ≥6 blocks; 999 permutations default | correlations/refusals + confidence | missing values masked; insufficient coverage/contrast → explicit refusal, not 0 | [scanAssociations][S-assoc] | MIT |
| OpenStrap | circadian/alertness [A+B] | social jetlag, cosinor, nonparametric IS/IV/RA, 2-process alertness forecast | onset/wake or high-resolution activity/sleep | multi-day/within day, function-specific | timing/regularity/forecast | short/flat series→absent or reduced confidence; forecast can mark assumed phase | [socialJetlag][S-circ], [circadianNonparametric][S-np], [alertnessForecast][S-alert] | MIT |
| OpenStrap | physiological extras [A+B] | respiration estimates, nocturnal RHR/HR dip, HR recovery, temperature baseline, relative desaturation | raw RR/HR/accelerometry/temperature/SpO₂ (sensor-specific) | sleep/workout windows | measurement/trend/confidence | each has coverage gate; relative ADC not absolute clinical SpO₂ | [nocturnalRhr][S-noct], [hrRecovery][S-hrr], [tempCircadian][S-temp] | MIT |
| GenieMax | activity/training extras [A+B] | HR zones, calories from steps/weight/height, training effect, VO₂/fitness-age estimates | HR/time, steps, age/sex/size, workouts | workout/day/history | energy, load, age estimate | fallbacks are model assumptions; no HR/anthropometrics reduces scope | [Physiology][G-phys], [Workout][G-work] | MIT |

## Algorithm provenance и расхождения с описаниями

| Группа | Происхождение | Что именно не следует утверждать |
|---|---|---|
| RMSSD/SDNN/pNN50 из **реальных** NN/RR, Pearson, EWMA, z, Karvonen HRR, Banister/Edwards TRIMP, CTL/ATL/TSB, Phillips SRI | **A**: формулы/статистика опубликованы; реализации имеют собственные guards и соглашения об окне | Одинаковое имя метрики не гарантирует одинаковую очистку, SD convention, seed, timezone или достоверность датчика. |
| Sleep composite weights, recovery weights, шкалы strain, «возраст», resilience, illness thresholds, sleep debt accounting | **B**: формула видна в коде и может быть воспроизведена | Значения весов/порогов и интерпретация score не являются универсальным физиологическим стандартом. |
| WHOOP-подобные recovery/strain/sleep, Oura-подобный resilience | **C**: интерфейс/диапазон вдохновлён продуктом с закрытым алгоритмом | Это не точная копия WHOOP/Oura/Garmin, даже если использованы Banister или опубликованные компоненты. |
| [Vitals docs](https://github.com/DocStream-Oficial/vitals/blob/fb3a837/docs/ALGORITHMS.md) vs [`app/scoring.py`][V-score] | Документ описывает percentile recovery v2 (и quality gate «≥2 или не extreme»), но `RECOVERY_ANCHORED=True` делает **активным v3**: rolling mean/SD + logistic и gate HRV-or-sleep. | Для воспроизведения текущих результатов использовать ветку v3, а не текст таблицы README. |
| [Open Wearables docs](https://github.com/the-momentum/open-wearables/blob/fd78bdd/docs/scores/resilience-score.mdx) vs [service][O-res-svc] | Документация требует ≥20 HR samples/night и говорит о RMSSD, а действующий score читает **готовые RMSSD points** и проверяет ≥5 дней; min 20 применяется только к отдельным BPM-derived helper methods. SDNN fallback в service закомментирован, несмотря на часть docstrings. | Не считать BPM helper источником настоящего HRV и не приписывать score несуществующий 20-RR/night gate. |
| [GenieMax `sri`][G-daily] vs [Phillips SRI][S-sri] | Первая функция использует SD onset/wake. Вторая сравнивает sleep/wake состояния в одинаковые часы соседних суток. | Не объединять их как одну и ту же SRI метрику. |
| [NOOP strain][N-strain] | Текущая Swift-реализация Effort выдаёт **0–100** логарифмически; старые описания WHOOP-style 0–21 могут относиться к иной версии/экрану. | Проверять версию и output scale перед сравнением. |
| [asleep metadata][A-meta] vs [LICENSE.md][A-license] | Pyproject classifier указывает MIT, текст лицензии ограничивает использование академическими некоммерческими исследованиями. | Не трактовать `asleep` как MIT/разрешённый для личного consumer или коммерческого продукта без отдельной лицензии. |

## Качество реализации: проверяемые свойства

`✓` = свойство видно в коде/тестах, `част.` = только для части функций, `—` = не обнаружено в проверенных файлах. Это **не рейтинг**.

| Project | Unit / golden | Формула в коде | Missing / outliers | Baseline и cold start | Timezone / version |
|---|---|---|---|---|---|
| NOOP | Swift и Kotlin tests, паритет; golden-like vectors в test suite | ✓, constants названы | ✓ для RR, RHR, sleep; часть fallbacks намеренно сохраняет score | EWMA status seed/trusted/stale | local day handling в engine/tests; mirrored repo snapshot фиксировать SHA |
| Vitals | pytest regression/engine v3/sleep/healthspan | ✓, `ALGORITHMS.md` частично устарел | `None` для многих score; sleep debt только deficits; raw HRV QC ограничен | 30 чтений/90 d, EWMA, cold fallback | ISO date keys; engine version в summary, UTC/local semantics зависят от source adapter |
| GenieMax | Swift tests и `*_golden.json` | ✓ | HRV/RHR gating; optional z=0; есть функции, где отсутствующие stage поля становятся нулём | EWMA ≥7, pre-update night comparison | night/window helpers; version via pinned commit/golden fixtures |
| Open Wearables | pure score tests + DB integration tests | ✓ | sleep missing stage=0; resilience null on missing RMSSD; BPM-derived HRV методологически неверен | sleep history 14; HRV CV 5/7 | score service учитывает zone offset; resilience grouping **UTC date**; migrations |
| Pulse | `SelfTest` executable, нет столь широких golden fixtures в snapshot | ✓ | reweight missing recovery, neutral fallback при короткой истории; strain steps proxy | 30 values, reliable ≥5 | `DayKey`, `Calendar.current` в sleep timing; SHA/version external |
| OpenStrap | extensive tests + recorded-night fixtures | ✓ и `Metric<T>.note` | явные отказ/coverage/quantum guards; обратите внимание на SRI pair-total nuance | robust baseline, ≥14 canonical readiness | calendar grid для associations; deterministic SHA/test fixtures |
| NeuroKit2 | upstream test suite, scientific docs | ✓ | NaN для коротких HRV windows; peak QC upstream | не является recovery engine | sampling rate + RR timestamps; pin package version |
| FLIRT | package tests | ✓ | sliding windows могут дать NaN; clean_data configurable | не является readiness engine | datetime windows; старый код требует проверять timezone readers |
| pyHRV | тестовые данные/примеры; coverage по функциям неоднородно | ✓ | отдельные функции могут warn/raise | не является readiness engine | NNI/window duration; pin release |
| HeartPy | package tests/examples | ✓ | peak rejection; warnings/errors зависят от функции | не является readiness engine | sample rate обязателен; pin release |
| asleep | model/e2e tests, опубликованная validation dataset; нет простого portable golden-vector для Xiaomi | learned weights + preprocessing | non-wear/sleep gaps; raw accel обязателен | модель, не personal baseline | 30s epochs; pre-download weights для полностью offline; academic license |

## Licensing

Таблица относится к **копированию/подключению кода**, а не к чтению математической идеи. Это техническая инвентаризация лицензий, не индивидуальная юридическая консультация.

| Код | Личное применение | Возможное коммерческое применение | Условия/ограничения |
|---|---|---|---|
| NOOP | Да, некоммерческое | **Нет по текущей PolyForm NC**; потребуется отдельное разрешение | сохранить PolyForm/notice; факт формулы и код имеют разный правовой режим |
| Vitals, GenieMax, Open Wearables, OpenStrap, NeuroKit2, HeartPy | Да | Да, MIT | сохранить copyright/license; проверить лицензии зависимостей и данных |
| Pulse | Да | Да, Apache-2.0 | LICENSE/NOTICE, изменение файлов и патентные условия |
| pyHRV | Да | Да, BSD-3-Clause | сохранить license/disclaimer |
| FLIRT HRV/ACC | Да | Да, MIT | при включении **cvxEDA** отдельная GPL-3.0 оговорка в LICENSE |
| OxWearables asleep | **Не для обычного consumer use** по тексту licence | **Нет** без отдельного договора | только внутреннее академическое некоммерческое исследование; pyproject classifier MIT противоречит LICENSE.md |

## Reusable components

- NOOP: `Packages/StrandAnalytics` содержит математику, тесты и типы, но его исходный код нельзя переносить в будущий коммерческий проект по текущей лицензии.
- Vitals: `app/load.py`, `app/sleep_scores.py`, `app/trends.py` почти чистые функции стандартной библиотеки; `scoring.py` требует его дневной словарь/профиль.
- GenieMax: `Sources/GenieMax/{HRV,Scores,Baseline,RecoveryEngine,SleepStaging}.swift` — отдельные файлы; целый SwiftPM package тянет Sodium для других функций.
- Open Wearables: `backend/app/algorithms/{sleep,resilience,scoring_primitives}.py` отделимы; `services/scores` привязаны к SQLAlchemy/Postgres и источникам данных.
- Pulse: `Core/Metrics/*.swift` образуют отдельный `PulseCore`; input contracts `DayRecord` и `SleepSession` определены в `Core/Models`.
- OpenStrap: `lib/src/onehz` — pure Dart с явным `Metric<T>` quality contract; особенно автономны HRV, TRIMP/load, SRI, baseline, associations.
- NeuroKit2/FLIRT/pyHRV/HeartPy: переносимы как пакеты анализа **сигнала**, когда есть настоящий ECG/PPG/NN. Они не заменяют recovery score.
- `asleep` технически предлагает валидированную sleep-stage ML pipeline, но требует сырой акселерометрии/весов и лицензии для желаемого вида использования.

## Missing areas перед этапом выбора

1. Нет стандартного, доказанно корректного способа вывести HRV/RMSSD/SDNN из отдельных BPM-точек Mi Band 10. Если source не содержит настоящих RR/IBI либо device-reported HRV, HRV-dependent score остаётся неполным; это не следует маскировать расчётом `60000/BPM` между измерениями.
2. Нужен собственный контракт сопоставления **конкретных** полей Xiaomi с inputs каталогов: timezone, source/local date, единицы, sleep-session boundaries, vendor-derived vs raw, дубли, достаточное покрытие HR samples. Выбор правил — следующий этап, не это исследование.
3. Нет переносимого универсального определения recovery/readiness/sleep need и валидированной шкалы 0–21 для любых часов. Готовые открытые реализации дают варианты, а их недостающие компоненты обрабатываются по-разному.
4. Для признаков болезни/восстановления нужны правила качества, персональная калибровка и проверка ложных срабатываний на локальной истории; OSS implementations показывают методы, но не сертифицированную диагностику.
5. Отдельно требуется определить, считать ли готовый Xiaomi sleep/stress/vitality score самостоятельным наблюдением, входом чужой формулы или только baseline для сопоставления. Его proprietary алгоритм неизвестен.

## Закреплённые source links

[N-license]: https://github.com/ParthJadhav/noop/blob/63f3ed0/LICENSE
[N-package]: https://github.com/ParthJadhav/noop/tree/63f3ed0/Packages/StrandAnalytics
[N-rec]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/RecoveryScorer.swift
[N-hrv]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/HRVAnalyzer.swift
[N-freq]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/HRVFreqDomain.swift
[N-base]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/Baselines.swift
[N-strain]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/StrainScorer.swift
[N-ana]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/AnalyticsEngine.swift
[N-debt]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/SleepDebt.swift
[N-ready]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/ReadinessEngine.swift
[N-ill]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/IllnessSignalEngine.swift
[N-corr]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/CorrelationEngine.swift
[N-effect]: https://github.com/ParthJadhav/noop/blob/63f3ed0/Packages/StrandAnalytics/Sources/StrandAnalytics/EffectRanker.swift
[V-license]: https://github.com/DocStream-Oficial/vitals/blob/fb3a837/LICENSE
[V-score]: https://github.com/DocStream-Oficial/vitals/blob/fb3a837/app/scoring.py
[V-load]: https://github.com/DocStream-Oficial/vitals/blob/fb3a837/app/load.py
[V-sleep]: https://github.com/DocStream-Oficial/vitals/blob/fb3a837/app/sleep_scores.py
[V-insights]: https://github.com/DocStream-Oficial/vitals/blob/fb3a837/app/insights.py
[V-age]: https://github.com/DocStream-Oficial/vitals/blob/fb3a837/app/bodyage.py
[V-span]: https://github.com/DocStream-Oficial/vitals/blob/fb3a837/app/healthspan.py
[V-trends]: https://github.com/DocStream-Oficial/vitals/blob/fb3a837/app/trends.py
[G-license]: https://github.com/satayutata/geniemax-core/blob/4765501/LICENSE
[G-rec]: https://github.com/satayutata/geniemax-core/blob/4765501/Sources/GenieMax/RecoveryEngine.swift
[G-scores]: https://github.com/satayutata/geniemax-core/blob/4765501/Sources/GenieMax/Scores.swift
[G-hrv]: https://github.com/satayutata/geniemax-core/blob/4765501/Sources/GenieMax/HRV.swift
[G-base]: https://github.com/satayutata/geniemax-core/blob/4765501/Sources/GenieMax/Baseline.swift
[G-daily]: https://github.com/satayutata/geniemax-core/blob/4765501/Sources/GenieMax/DailyMetrics.swift
[G-stage]: https://github.com/satayutata/geniemax-core/blob/4765501/Sources/GenieMax/SleepStaging.swift
[G-phys]: https://github.com/satayutata/geniemax-core/blob/4765501/Sources/GenieMax/Physiology.swift
[G-work]: https://github.com/satayutata/geniemax-core/blob/4765501/Sources/GenieMax/Workout.swift
[O-license]: https://github.com/the-momentum/open-wearables/blob/fd78bdd/LICENSE
[O-sleep]: https://github.com/the-momentum/open-wearables/blob/fd78bdd/backend/app/algorithms/sleep.py
[O-sleep-svc]: https://github.com/the-momentum/open-wearables/blob/fd78bdd/backend/app/services/scores/sleep_service.py
[O-res]: https://github.com/the-momentum/open-wearables/blob/fd78bdd/backend/app/algorithms/resilience.py
[O-res-svc]: https://github.com/the-momentum/open-wearables/blob/fd78bdd/backend/app/services/scores/resilience_service.py
[P-license]: https://github.com/Luraxx/pulse/blob/1f8975c/LICENSE
[P-rec]: https://github.com/Luraxx/pulse/blob/1f8975c/Core/Metrics/RecoveryEngine.swift
[P-stats]: https://github.com/Luraxx/pulse/blob/1f8975c/Core/Metrics/Stats.swift
[P-monitor]: https://github.com/Luraxx/pulse/blob/1f8975c/Core/Metrics/HealthMonitor.swift
[P-strain]: https://github.com/Luraxx/pulse/blob/1f8975c/Core/Metrics/StrainEngine.swift
[P-sleep]: https://github.com/Luraxx/pulse/blob/1f8975c/Core/Metrics/SleepEngine.swift
[P-age]: https://github.com/Luraxx/pulse/blob/1f8975c/Core/Metrics/AgeEngine.swift
[S-license]: https://github.com/OpenStrap/analytics/blob/0441ef9/LICENSE
[S-rr]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/foundations/rr_correction.dart
[S-hrv]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/clinical/hrv_time.dart
[S-ln]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/clinical/readiness_lnrmssd.dart
[S-ready]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/wellness/readiness_composite.dart
[S-glass]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/human/readiness_glassbox.dart
[S-cusum]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/clinical/illness_cusum.dart
[S-anomaly]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/wellness/anomaly.dart
[S-load]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/clinical/load_trimp.dart
[S-over]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/human/overreaching_conjunction.dart
[S-debt]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/human/sleep_regularity.dart
[S-sri]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/sleep/sri.dart
[S-van]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/sleep/van_hees.dart
[S-nap]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/sleep/nap.dart
[S-assoc]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/human/associations.dart
[S-circ]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/human/circadian_lifestyle.dart
[S-np]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/sleep/circadian_np.dart
[S-alert]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/human/alertness_forecast.dart
[S-noct]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/clinical/nocturnal.dart
[S-hrr]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/workout/hr_recovery.dart
[S-temp]: https://github.com/OpenStrap/analytics/blob/0441ef9/lib/src/onehz/wellness/temp_circadian.dart
[K-hrv]: https://raw.githubusercontent.com/neuropsychology/NeuroKit/ff419d983568ef492eb8d229af643c0ef0100b32/neurokit2/hrv/hrv_time.py
[K-freq]: https://raw.githubusercontent.com/neuropsychology/NeuroKit/ff419d983568ef492eb8d229af643c0ef0100b32/neurokit2/hrv/hrv_frequency.py
[F-license]: https://github.com/im-ethz/flirt/blob/d9bdcc5/LICENSE
[F-hrv]: https://github.com/im-ethz/flirt/blob/d9bdcc5/flirt/hrv/feature_calculation.py
[Y-license]: https://github.com/PGomes92/pyhrv/blob/e90219c/LICENSE.txt
[Y-time]: https://github.com/PGomes92/pyhrv/blob/e90219c/pyhrv/time_domain.py
[Y-freq]: https://github.com/PGomes92/pyhrv/blob/e90219c/pyhrv/frequency_domain.py
[Y-nl]: https://github.com/PGomes92/pyhrv/blob/e90219c/pyhrv/nonlinear.py
[H-license]: https://github.com/paulvangentcom/heartrate_analysis_python/blob/ef48d23/LICENSE
[H-analysis]: https://github.com/paulvangentcom/heartrate_analysis_python/blob/ef48d23/heartpy/analysis.py
[A-license]: https://github.com/OxWearables/asleep/blob/79a9f65/LICENSE.md
[A-meta]: https://github.com/OxWearables/asleep/blob/79a9f65/pyproject.toml
[A-model]: https://github.com/OxWearables/asleep/blob/79a9f65/src/asleep/sslmodel.py
[A-stats]: https://github.com/OxWearables/asleep/blob/79a9f65/src/asleep/sleep_stats.py
