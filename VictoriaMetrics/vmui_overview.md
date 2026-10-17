# vmui: веб-интерфейс VictoriaMetrics

**Актуально для:** VictoriaMetrics v1.154.0 (VMUI поставляется в составе бинарников `victoria-metrics`/`vmselect` и меняется вместе с версией сервера)

## Определения

**vmui (VMUI)** — встроенный веб-интерфейс для отладки запросов и исследования данных, доступный на HTTP-порту самого компонента: у single-node — `http://localhost:8428/vmui`, у кластерного `vmselect` — `http://<vmselect>:8481/select/<accountID>/vmui/`. Статика UI зашита в бинарник, отдельного сервиса не требуется; UI ходит в тот же HTTP API компонента (`/api/v1/query`, `/api/v1/status/*`). Это «экспресс-инструмент инженера» для проверки данных, поиска медленных запросов и диагностики кардинальности без настройки Grafana.

**Cardinality Explorer** — вкладка исследования кардинальности TSDB: топ метрик, лейблов и их значений за выбранный день; построен на `/api/v1/status/tsdb`.

**Top queries / Active queries** — вкладки статистики запросов поверх `/api/v1/status/top_queries` и `/api/v1/status/active_queries`: что выполнялось, что выполняется сейчас и кто это запустил.

**Query analyzer / Trace analyzer** — инструменты разбора экспортированных JSON с результатом запроса и trace-трассой; загружаются обратно в vmui (Tools → Query Analyzer).

**Metric relabel debugger** — пошаговый отладчик правил relabeling: для каждого правила показываются входные и выходные лейблы серии.

У VictoriaLogs на порту `9428` — собственный форк того же UI для запросов LogsQL (`/vmui`); метрический VMUI описывается здесь, логи — в [logsql_overview.md](./logsql_overview.md).

## Базовые концепции

### Возможности по вкладкам

| Вкладка / инструмент | Назначение |
| :--- | :--- |
| **Query** | Ad-hoc запросы MetricsQL: графики (time series), таблицы, гистограммы; автодополнение функций/метрик/лейблов (тумблер Autocomplete, `Ctrl+Space`); несколько запросов на одном графике (Add Query) |
| **Raw Query** (с v1.107.0) | «Сырые» необработанные сэмплы без агрегации — виден реальный scrape-интервал, дубликаты сэмплов; экспорт в CSV |
| **Explore → Metrics explorer** | Выбор `job`/`instance` → автоматическое построение графиков по выбранным метрикам |
| **Explore → Cardinality explorer** | Топ метрик/лейблов/значений за день, фильтр series selector, статистика использования метрик |
| **Explore → Top queries** | Самые частые, самые долгие (avg/суммарно), самые «прожорливые» по памяти запросы |
| **Explore → Active queries** | Выполняющиеся прямо сейчас запросы: выражение, time range/step, длительность, адрес клиента |
| **Tools → Trace analyzer** | Разбор query trace, загруженного из JSON |
| **Tools → Query analyzer** | Разбор запроса с трассой, экспортированного из Query-вкладки (иконка debug над trace-блоком) |
| **Tools → WITH playground** | Проверка работы WITH-выражений MetricsQL |
| **Tools → Metric relabel debugger** | Пошаговый прогон серии через relabeling-правила (вход/выход лейблов) |
| **Tools → Downsampling / Retention filters debuggers** (с v1.105.0) | Отладка Enterprise-конфигов downsampling и retention filters |
| **Dashboards** | Предопределённые дашборды, создание/экспорт/импорт своих JSON; свои шаблоны — через `-vmui.customDashboardsPath` |
| **Alerting** (с v1.125.0) | Просмотр групп и правил vmalert; появляется только при настроенном `-vmalert.proxyURL` на vmsingle/vmselect |

### Управление графиком и запросом

- **Step** автоматически подбирается под ширину экрана и time range; можно задать вручную (правый верхний угол). Значение из URL (`g0.step_input`) сохраняется при открытии ссылки.
- **Time range**: пикер (relative/`From`–`To`), зум выделением области, `Ctrl/Cmd` + скролл — зум, `Ctrl/Cmd` + перетаскивание — сдвиг диапазона.
- **Легенда**: клик — скрыть все остальные серии, `Ctrl`+клик — только эту; клик по паре `label=value` копирует значение; переключение в table view, скрытие общих лейблов; с v1.152.0 в легенде виден диапазон min–max по каждой линии.
- **История запросов**: `Ctrl`/`Cmd` + `↑`/`↓` при курсоре в поле запроса.
- **Гистограммы**: при результате с bucket-сериями (Prometheus- и VM-гистограммы) vmui сам переключается в heatmap; отключается тумблером `Histogram mode` в настройках графика.
- **Автозум/авто-обновление**: интервал авто-обновления задаётся в выпадающем списке кнопки Execute (с v1.153.0) и запоминается в URL (с v1.149.0).

### Отладка запросов внутри vmui

- **Disable cache** — чекбокс под запросом: отключает rollup result cache; полезен при backfill и отладке неожиданных результатов (см. [troubleshooting](https://docs.victoriametrics.com/victoriametrics/troubleshooting/)).
- **Trace query** — тумблер под полем запроса: генерирует trace выполнения, клик по трассе раскрывает детали; экспорт — иконка debug над trace-блоком, файл загружается в Tools → Query Analyzer.
- **Raw Query** — страница сырых сэмплов: диагностика фактического scrape-интервала и дубликатов.

### Отличие от Grafana

- **Быстрее**: zero-dependency, ничего настраивать не нужно; работает, даже когда Grafana недоступна — vmui живёт в том же процессе, что и хранилище.
- **Точечнее**: весь MetricsQL + встроенные анализаторы (queries, cardinality, relabel) в одном месте; инженерный инструмент для инцидентов.
- **Уже**: не заменяет платформу дашбордов и командный доступ — для дашбордов, RBAC и общих datasource используйте [grafana_integration.md](./grafana_integration.md).

### Зачем это в заметках

vmui — первая линия диагностики: «есть ли данные», «какой запрос висит и кто его запустил», «что взорвало кардинальность после релиза», «почему relabeling срезал не те лейблы». Знание vmui — практический ответ на интервью-вопросы о диагностике TSDB и повседневный SRE-инструмент.

## Практические сценарии

### 1. Быстрая проверка данных

Откройте `http://localhost:8428/vmui` и выполните:

```text
up
```

```text
rate(node_cpu_seconds_total[5m])
```

График сразу отвечает на вопросы «есть ли данные» (включая данные за выбранный time range) и «что сейчас происходит с нагрузкой».

### 2. Диагностика медленных и тяжёлых запросов (SRE)

1. **Active queries** (Explore) — что выполняется прямо сейчас: выражение, time range/step, длительность, **адрес клиента**. Тяжёлый запрос в проде виден здесь без ожидания.
2. **Top queries** — накопленная статистика: частые запросы, наибольшая средняя длительность, наибольшая суммарная длительность, наибольшее потребление памяти. Источник — `/api/v1/status/top_queries` (см. [http_api_reference.md](./http_api_reference.md)).
3. Включите **Trace query** на подозрительном запросе, изучите трассу, экспортируйте через debug-иконку и откройте в **Query analyzer** — там видно, какие стадии и сколько серий реально обработано.
4. Сузьте selector, добавьте агрегацию (`topk`, `sum by (...)`), уменьшите time range — и перепроверьте.
5. Для backfill/подозрительных значений — **Disable cache** и **Raw Query**.

### 3. Диагностика кардинальности после релиза

1. Откройте **Explore → Cardinality explorer**: по умолчанию анализируется текущий день; днем ранее/позже можно выбрать в правом верхнем углу — сравнение «до/после» ловит взрыв кардинальности без запросов к API.
2. Топ по метрикам; клик по метрике — разрез по лейблам (focusLabel); дальше — топ значений лейбла и пары `label=value`.
3. Вкладка usage статистики показывает, сколько раз метрика запрашивалась и когда последний раз (`Requests count` / `Last request`) — бесполезно чистить метрику, которую никто не читает, и наоборот.
4. Сузьте анализ series selector'ом, если нужен только один `job`.
5. Для постоянного мониторинга и алертинга кардинальности — [vmestimator](./vmestimator.md) (проактивные метрики), для точечной диагностики хранимых серий — `/api/v1/status/tsdb` ([http_api_reference.md](./http_api_reference.md)).

Ограничение кластера: при репликации или rerouting одни и те же серии могут лежать на нескольких `vmstorage`, и vmselect суммирует статистику — значения кардинальности могут быть завышены.

### 4. Отладка relabeling перед выкаткой конфига

1. Откройте **Tools → Metric relabel debugger**.
2. Вставьте relabeling-правила (те же, что планируете на vmagent/vminsert) и тестовую серию.
3. Пошагово видно, как каждое правило меняет лейблы: какой `if` совпал, что осталось на выходе, где серия была отброшена.
4. Только после проверки переносите правила в рабочий конфиг ([vmagent_overview.md](./vmagent_overview.md)).

Связанные отладчики `Downsampling filters` и `Retention filters` (v1.105.0+) — для Enterprise-конфигов.

### 5. Работа с дашбордами

- Готовые дашборды — вкладка Dashboards; свои шаблоны положите в каталог и укажите флагом:

```bash
victoria-metrics \
  -httpListenAddr=:8428 \
  -storageDataPath=/victoria-metrics-data \
  -vmui.customDashboardsPath=/etc/victoria-metrics/vmui-dashboards
# → дашборды из каталога появятся в списке vmui
```

- Экспортируйте созданные дашборды в JSON и храните в Git — изменения прослеживаются ревью, а не «в голове».
- Ссылка на конкретный запрос/график шарится через URL состояния vmui.

### 6. Alerting tab: правила vmalert внутри vmui

Вкладка Alerting (с v1.125.0) показывает группы и правила vmalert, но появляется только если vmsingle (или `vmselect` в кластере) настроен флагом:

```bash
victoria-metrics \
  -httpListenAddr=:8428 \
  -storageDataPath=/victoria-metrics-data \
  -vmalert.proxyURL=http://vmalert:8880
# → запросы вида /api/v1/rules из vmui проксируются на vmalert
```

Обратная связь (ссылки из алертов vmalert на график в vmui) настраивается на стороне vmalert флагами `-external.url` и `-external.alert.source` — см. [vmalert_overview.md](./vmalert_overview.md). Более широкий пользовательский доступ — через Grafana ([grafana_integration.md](./grafana_integration.md)).

### 7. Кластерный режим и мультитенантность

- URL vmui в кластере: `http://<vmselect>:8481/select/<accountID>/vmui/` — `accountID` (и опционально `projectID`) определяют тенанта. С v1.150.0 multitenancy via headers включена по умолчанию, упрощённые URL без tenant ID в пути тоже валидны.
- Тенант и server URL хранятся в настройках vmui; начиная с v1.154.0 их нельзя переопределить query-параметрами (защита от подмены ссылкой).
- vmui — UI одного выборочного контура; обзор всех тенантов удобнее делать Grafana-datasource'ами через vmauth ([grafana_integration.md](./grafana_integration.md), [vmauth_overview.md](./vmauth_overview.md)).
- Часовой пояс UI задаётся флагом `-vmui.defaultTimezone` (IANA-имя, например `Europe/Berlin` или `Local`); UTC-смещение выбранной зоны видно рядом с контролами даты.

### 8. Доступ к vmui в Kubernetes (порт-форвард)

```bash
# vmsingle из чарта victoria-metrics-k8s-stack (порт сервиса 8428)
kubectl -n monitoring port-forward svc/victoria-metrics-k8s-stack-vmsingle 8428:8428
# → http://localhost:8428/vmui

# кластер: vmselect
kubectl -n monitoring port-forward svc/victoria-metrics-vmselect 8481:8481
# → http://localhost:8481/select/0/vmui/
```

Команда и имена сервисов чарта — в [helm_victoria_metrics_k8s_stack.md](./helm_victoria_metrics_k8s_stack.md).

### 9. Безопасность доступа к vmui

- vmui живёт на HTTP-порту компонента и **не имеет собственной аутентификации** — закрывайте порт firewall'ом и ставьте перед ним [vmauth](./vmauth_overview.md) или reverse proxy с TLS/Basic auth (флаги `-httpAuth.*`, `-tls*`); детали — в [security.md](./security.md).
- Известные XSS в vmui исправлены в v1.152.0 (страница relabeling, GHSA-vw10j-rqhg-qff9) и v1.154.0 (Metric Relabeling Debug, Query Analyzer, Dashboards, GHSA-m2x2-9xpq-mmq5) — для интернет-facing доступа обновляйтесь до v1.154.0+.
- Не отправляйте коллегам ссылки с неизвестными query-параметрами: до v1.154.0 server URL/тенант/тема могли переопределяться через URL.

## Валидация

```bash
# 1. Страница vmui отвечает
curl -s http://localhost:8428/vmui | grep -q "<!DOCTYPE" && echo "vmui OK"
# → vmui OK

# 2. Тот же язык запросов доступен напрямую через API
curl -s 'http://localhost:8428/api/v1/query?query=up' | jq '.data.result | length'
# → 12   (число серий up)

# 3. Источники данных вкладок Top/Active queries живы
curl -s http://localhost:8428/api/v1/status/top_queries | jq 'keys'
# → [...]
curl -s http://localhost:8428/api/v1/status/active_queries | jq '.data.activeQueries | type'
# → "array"

# 4. Кластерный URL vmui (тенант 0)
curl -sI http://vmselect:8481/select/0/vmui/ | head -1
# → HTTP/1.1 200 OK

# 5. Alerting tab: прокси на vmalert настроен (проверка с vmsingle)
curl -s http://localhost:8428/api/v1/rules | jq '.data.groups | length'
# → 8   (без -vmalert.proxyURL вернётся ошибка/пустой ответ VM)
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| 404 на `/vmui` | Не тот порт; в кластере пропущен префикс `/select/<accountID>` | Single: порт `-httpListenAddr` (по умолчанию 8428); кластер: `http://vmselect:8481/select/<accountID>/vmui/` |
| Запрос в vmui работает, в Grafana нет (и наоборот) | Разные datasource/time range/URL-форматы кластера | Сверить URL datasource и time range ([grafana_integration.md](./grafana_integration.md)) |
| «Too many time series» | Слишком широкий selector | Сузить фильтр, `topk(...)`, уменьшить time range |
| График обрывается, «дырки» | Пустые интервалы, слишком крупный step | Уменьшить step; для «последнего значения» — `keep_last_value` ([metricsql_reference.md](./metricsql_reference.md)) |
| vmui тормозит на проде | Тяжёлые запросы через UI нагружают vmselect | Ограничивать time range; лимиты `-search.max*` — в [http_api_reference.md](./http_api_reference.md); Disable cache делает запрос ещё дороже |
| Нет вкладки Alerting | Не задан `-vmalert.proxyURL` | Добавить флаг vmsingle/vmselect (см. сценарий 6) |
| Cardinality explorer завышает значения (кластер) | Репликация/rerouting: серии на нескольких vmstorage суммируются | Учитывать кавердюк; для точных цифр сверяться с `/api/v1/status/tsdb` |
| Вместо линий — heatmap | Автовключение Histogram mode для bucket-серий | Выключить `Histogram mode` в настройках графика |
| UI отличается от описаний/скриншотов | VMUI привязан к версии сервера | Сверять с changelog своей версии; после апгрейда VM перезагрузить страницу (кэш статики) |

## Рекомендации по эксплуатации

- Используйте vmui как **первичную** проверку до создания панели в Grafana — это экономит CPU Grafana и время дежурного.
- Дашборды vmui, которыми пользуется команда, храните как JSON в Git (`-vmui.customDashboardsPath`) — это единственный способ прослеживать их изменения.
- Раз в месяц смотрите Top queries: накопленная статистика показывает «шумные» запросы, которые не видны в момент инцидента.
- Кардинальность мониторьте планово (Cardinality Explorer после релизов) и непрерывно ([vmestimator](./vmestimator.md)); разборы — в сценарии 3.
- Не открывайте порты компонентов наружу: vmui, API и admin-эндпоинты делят один порт ([security.md](./security.md)).
- Апгрейд VM улучшает и vmui (новые вкладки, фиксы UX по changelog) — обновляйте сервер, а не только Grafana.

## Ограничения и особые случаи

- vmui — инструмент одного инстанса и одного выборочного контура; мульти-тенантный обзор — через Grafana + vmauth.
- Версия UI фиксирована версией сервера: отдельно «поднять свежий vmui» над старым хранилищем нельзя (кроме ручного указания Server URL в настройках; редактирование Server URL deprecate-ится в tip-сборках).
- Cardinality explorer в кластере может завышать статистику (репликация/rerouting, см. сценарий 3).
- Downsampling/Retention filters debuggers относятся к Enterprise-функциям — в Community UI вкладки соответствующих конфигов не будет.
- Trace/Query analyzer работают с JSON, экспортированным из vmui: трассы других форматов туда не загрузить.
- Для командного развёртывания дашбордов, алертинга и RBAC используйте Grafana — vmui не заменяет её ([grafana_integration.md](./grafana_integration.md)).

## Дополнительная информация

### Ссылки

- [Документация VictoriaMetrics, раздел vmui](https://docs.victoriametrics.com/victoriametrics/#vmui) — официальный источник возможностей UI;
- [VMUI на playground](https://play.victoriametrics.com?g0.expr=up) — демонстрация без установки;
- [Cardinality Explorer: blog post](https://victoriametrics.com/blog/cardinality-explorer/) — мотивация и примеры анализа;
- Примеры дашбордов UI: [app/vmui/public/dashboards](https://github.com/VictoriaMetrics/VictoriaMetrics/tree/master/app/vmui/packages/vmui/public/dashboards).

### См. также

- [VictoriaMetrics: обзор](./overview.md) — порты, запуск single-node;
- [HTTP API: диагностика](./http_api_reference.md) — `/api/v1/status/tsdb`, `active_queries`, `top_queries`;
- [MetricsQL: справочник](./metricsql_reference.md) — синтаксис запросов в vmui;
- [vmalert: алертинг](./vmalert_overview.md) — вкладка Alerting, `-external.url`/`-external.alert.source`;
- [vmestimator](./vmestimator.md) — непрерывный мониторинг кардинальности;
- [Grafana: интеграция](./grafana_integration.md) — командные дашборды вместо/вместе с vmui;
- [security.md](./security.md) — защита HTTP-порта компонентов, XSS-фиксы vmui.
