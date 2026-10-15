# Полная наблюдаемость на одном VPS: метрики, логи, алерты, дашборды

**Актуально для:** VictoriaMetrics v1.136+, VictoriaLogs v1.52+, vmalert v1.136+, Grafana 11.x, k0s 1.30+

## Определения

**k0s** — минималистичный Kubernetes-дистрибутив от Mirantis, запускаемый как одиночный бинарник без внешних зависимостей. Подходит для edge, IoT и малых VPS.

**vmsingle** — режим работы VictoriaMetrics, объединяющий приём (vminsert), хранение и выполнение запросов (vmselect) в одном процессе. Заменяет Prometheus + оператор на одиночном узле. [Подробнее](../VictoriaMetrics/vmsingle_single_node.md)

**VictoriaLogs (single)** — одиночный бинарник VictoriaLogs, выполняющий все роли (vlinsert, vlstorage, vlselect) для хранения и запроса логов.

**Promtail** — агент сбора логов от Grafana, отправляет логи по протоколу Loki Push API. В данном стеке используется как DaemonSet для тейлинга access-логов Traefik.

**hostPath PV + Retain** — паттерн персистентного хранения: данные кладутся в каталог на хосте, `persistentVolumeReclaimPolicy: Retain` гарантирует сохранность при `helm uninstall`, а `storageClassName: ""` на PVC отключает ожидание провижионера.

## Архитектура решения

```
                     ┌──────────────────────────────────────────────┐
                     │                 Grafana :3000                │
                     │  datasources: VictoriaMetrics + VictoriaLogs │
                     └──────────┬─────────────────────┬─────────────┘
                                │ PromQL/MetricsQL    │ LogsQL
                                ▼                     ▼
         ┌─────────────────────────────┐   ┌──────────────────────┐
         │   vmsingle-server :8428     │   │  victoria-logs :9428 │
         │   scrape + store, 90d       │   │  store, 7d           │
         └──┬──────────────────────┬───┘   └──────────▲───────────┘
            │ scrapes              │ rules            │ loki push
            ▼                      ▼                  │
   node-exporter            ┌──────────┐       ┌──────┴─────┐
   kube-state-metrics       │ vmalert  │       │  promtail  │
   traefik :9101            └────┬─────┘       │ DaemonSet  │
   blackbox-exporter             │             └──────▲─────┘
   kubelet cadvisor              ▼                    │ tails
   proxy exporters        ┌──────────────┐    /var/log/pods/
                          │ alertmanager │──▶ Telegram   traefik_traefik-*
                          └──────────────┘
```

**Ключевые характеристики:**
- Два хранилища — по одному на тип сигнала (метрики / логи)
- Оба — одиночные бинарники семейства VictoriaMetrics
- Оба хранят на hostPath PV
- Оба опрашивает одна Grafana
- Всё, что ниже — stateless-обвязка

## Ресурсы и планирование

Цифры из манифестов (requests / limits):

| Компонент | CPU req | RAM req | CPU limit | RAM limit |
|-----------|---------|---------|-----------|-----------|
| vmsingle | 50m | 128Mi | 500m | 512Mi |
| victoria-logs | 10m | 32Mi | 200m | 128Mi |
| promtail | 10m | 32Mi | 100m | 64Mi |
| vmalert | 10m | 32Mi | 200m | 128Mi |
| alertmanager | 10m | 32Mi | 100m | 64Mi |
| node-exporter | 10m | 20Mi | 100m | 64Mi |
| kube-state-metrics | 10m | 32Mi | 200m | 128Mi |
| blackbox-exporter | 10m | 16Mi | 100m | 64Mi |
| grafana | 50m | 128Mi | 500m | 512Mi |
| **Итого** | **170m** | **452Mi** | **2000m** | **1664Mi** |

**Вывод:** 452 МБ requests на девять компонентов. Установка `kube-prometheus-stack` по умолчанию запрашивает больше под один только Prometheus. Сумма лимитов больше, чем есть у ноды — это нормально: пики не совпадают, планировщик ориентируется на requests.

**Хранилище:**
- vmsingle: 20 ГБ hostPath, retention 90 дней
- victoria-logs: 5 ГБ hostPath, retention 7 дней

## Путь метрик

**vmsingle** скрейпит всё сам — встроенный скрейпер принимает обычные Prometheus `scrape_configs` (подробности см. в [руководстве по vmsingle](../VictoriaMetrics/vmsingle_single_node.md)). 

**Таргеты:**
- node-exporter
- kube-state-metrics
- Traefik :9101
- kubelet cAdvisor (с маленьким ClusterRole на API kubelet'а)
- два экспортёра прокси
- сам vmsingle
- vmalert
- три blackbox-джоба:
    - HTTP-пробы девяти сайтов
    - TCP-проверки четырёх портов прокси
    - внешний DNS для связности

**vmalert** считает правила и пушит сработавшие алерты в alertmanager:
- сайт лежит
- медленный ответ
- SSL истекает раньше чем через 14 дней
- порт прокси недоступен
- деградация внешней связности
- давление по RAM/диску/CPU
- предсказание «диск заполнится через 4 часа»
- CrashLoop
- расхождение реплик

**alertmanager** доставляет в Telegram с шаблоном 🔴/✅ и inhibit-правилом: `critical` глушит свой же `warning`.

## Путь логов

1. **Traefik** пишет JSON access-логи в stdout (`logs.access.format: json` в values чарта)
2. **Kubelet** складывает их в `/var/log/pods/traefik_traefik-*/`
3. **Promtail** тейлит этот глоб — статическим путём, без Kubernetes service discovery — парсит JSON, поднимает `RequestMethod` и `DownstreamStatus` (и `ClientHost`, что безопасно только благодаря терпимости VictoriaLogs к кардинальности) в лейблы, отбрасывает известную шумную ошибку и пушит в VictoriaLogs по протоколу Loki
4. **VictoriaLogs** хранит 7 дней на томе в 5 ГБ: логи отвечают на «что только что случилось», историю хранят метрики

**Важное разделение:** ничего долгоживущего из логов не выводится. Частота запросов, проценты ошибков и гистограммы латентности берутся из собственного Prometheus-эндпоинта Traefik — хранить и запрашивать их так дешевле, чем когда-либо вышло бы считать их из access-логов.

## Развёртывание VictoriaLogs

VictoriaLogs развёртывается как обычный Deployment с hostPath-хранилищем. Ниже приведён полный манифест с пояснениями.

### VictoriaLogs Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: victoria-logs
  namespace: logging
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: victoria-logs
  template:
    metadata:
      labels:
        app: victoria-logs
    spec:
      tolerations:
        - operator: Exists
      containers:
        - name: victoria-logs
          image: victoriametrics/victoria-logs:v1.11.0-victorialogs
          args:
            - --storageDataPath=/data
            - --retentionPeriod=7d
            - --httpListenAddr=:9428
            - --loggerFormat=json
          ports:
            - containerPort: 9428
              name: http
          resources:
            requests:
              cpu: 10m
              memory: 32Mi
            limits:
              cpu: 200m
              memory: 128Mi
          volumeMounts:
            - name: data
              mountPath: /data
          livenessProbe:
            httpGet:
              path: /health
              port: 9428
            initialDelaySeconds: 10
            periodSeconds: 30
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: victoria-logs-data
```

### Три решения стоит проговорить

**strategy: Recreate.** Том — ReadWriteOnce hostPath. RollingUpdate, применяемый по умолчанию, попытался бы поднять новый под, пока старый ещё держит каталог с данными, — два писателя в одном каталоге это верный способ испортить LSM-дерево. Recreate сначала убивает старый под. Цена — несколько секунд простоя ингеста на каждый деплой, и это не важно: агенты буферизуют и повторяют отправку.

**Блок ресурсов.** 32 МБ request, лимит 128 МБ — это реальные цифры с работающего экземпляра, который принимает access-логи Traefik для девяти сайтов. В стабильном состоянии VictoriaLogs здесь сидит на 40–60 МБ.

**retentionPeriod=7d.** Access-логи — операционные данные, не архив. Недели хватает на вопросы «что случилось»; всё, что должно жить дольше — это метрика, и она уже лежит в VictoriaMetrics со сроком хранения 90 дней.

### Хранилище

Тот же паттерн, что и у тома для метрик — самодельный PV, прибитый к каталогу хоста, с явным биндингом:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: victoria-logs-data
spec:
  capacity:
    storage: 5Gi
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  hostPath:
    path: /var/lib/victoria-logs
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: victoria-logs-data
  namespace: logging
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 5Gi
  volumeName: victoria-logs-data
```

5 ГБ — намеренный запас. VictoriaLogs жмёт агрессивно: неделя access-логов этих сайтов занимает десятки МБ на диске. Запас нужен, чтобы добавление новых источников логов потом не превращалось в миграцию хранилища.

### Ингест: три протокола, ноль плагинов

Service — обычный ClusterIP на 9428. Один и тот же порт принимает:

    /insert/jsonline — родной формат VictoriaLogs
    /insert/loki/api/v1/push — протокол Loki, на котором говорят Promtail, Grafana Alloy и loki-sink Vector'а
    /insert/elasticsearch/_bulk — bulk API Elasticsearch, для Filebeat/Logstash

Это и есть практическая причина, почему VictoriaLogs так легко встраивается в существующую систему: любой агент, который вы уже умеете настраивать, шлёт в неё без модификаций. Мой агент доставки логов шлёт сюда:

```yaml
http://victoria-logs.logging.svc.cluster.local:9428/insert/loki/api/v1/push
```

### Запросы: VMUI и LogsQL

Встроенный UI живёт на :9428/select/vmui. Port-forward — и вперёд:

```bash
kubectl -n logging port-forward svc/victoria-logs 9428:9428
# → http://localhost:9428/select/vmui
```

LogsQL читается как конвейер. Селектор стрима, дальше фильтры:

```yaml
{job="traefik-access"}                                  # всё из одного стрима
{job="traefik-access"} DownstreamStatus:~"[45][0-9][0-9]"   # только 4xx/5xx
{job="traefik-access"} RequestPath:"/feed" _time:1h      # один путь, последний час
_time:5m error                                           # слово "error" где угодно, 5 минут
```

В отличие от Loki, фильтры по полям вроде DownstreamStatus:~"[45][0-9][0-9]" не требуют, чтобы поле было лейблом стрима — VictoriaLogs индексирует сами поля лога. Это снимает целое проектное упражнение «какие лейблы безопасны по кардинальности».

### Datasource в Grafana

Grafana нужен плагин victoriametrics-logs-datasource — ставится и провижинится из Helm values:

```yaml
plugins:
  - victoriametrics-logs-datasource

datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: VictoriaLogs
        type: victoriametrics-logs-datasource
        url: http://victoria-logs.logging.svc.cluster.local:9428
        access: proxy
```

После этого logs-панели в дашбордах принимают LogsQL-выражения напрямую.

### Что может пойти не так

Помимо общих проблем стека, у VictoriaLogs есть свои нюансы:

**Liveness-проба убивает под на старте.** После нечистого завершения VictoriaLogs проигрывает WAL до того, как начнёт отвечать `/health`. С коротким `initialDelaySeconds` kubelet прибивает её посреди реплея — и получается цикл рестартов. Для этого объёма данных хватает 10 секунд; если том больше — масштабируйте задержку вместе с ним (ровно этот класс проблем я уже ловил с другим stateful-подом на этой ноде и пришёл к `initialDelaySeconds: 30`).

**Дашборды из провижининга показывают «datasource not found».** Grafана назначает datasource случайный UID, если его не зафиксировать. Дашборд, закоммиченный с `"uid": "victorialogs"`, ломается, когда созданный через провижининг datasource получил UID `PD775F2863313E6C7`. Либо задавайте `uid: явно` в блоке провижининг, либо копируйте сгенерированный UID в JSON дашборда. Я выяснил это, разглядывая пустую logs-панель, которая прекрасно работала в Explore.

**Диск заполняется несмотря на retention.** Очистка по сроку хранения удаляет целые партиции и работает по расписанию — внезапный поток логов (бот долбит сайт, приложение застряло в цикле ошибок) может его обогнать. Лечится на стороне агента: шумные стримы надо дропать до отправки, а не фильтровать на этапе запросов.

## Дашборды

Grafana запровижинена, а не накликана:

- **Datasources** приходят из Helm values — VictoriaMetrics (тип prometheus, default) и VictoriaLogs через плагин `victoriametrics-logs-datasource`
- **Дашборды** — ConfigMap'ы с лейблом `grafana_dashboard: "1"`, их подбирает sidecar. Их пять: нода, Kubernetes, Traefik, прокси, VPN
- **Анонимный доступ** — только viewer; правки происходят в git

**Дашборд Traefik — место встречи обоих сигналов:**
- Панели per-service RPS, латентности, ошибок и трафика из метрик — лейбл `service` очищен от хеша relabel-правилом на этапе скрейпа
- Две logs-панели внизу на LogsQL:
  ```
  {job="traefik-access"}                                    # живой access-лог
  {job="traefik-access"} DownstreamStatus=~"[45][0-9][0-9]" # только ошибки
  ```
- Прыжок от «error rate вырос» к «вот конкретные упавшие запросы», не выходя из дашборда — ради этого вся неделя и была.

## Решения, которые повторяются
Ниже перечислены паттерны, использованные в этом стеке; подробное описание см. в [руководстве по vmsingle](../VictoriaMetrics/vmsingle_single_node.md).

Если перечитать компоненты подряд, одни и те же выборы видны в каждом:

| Паттерн | Реализация |
|---------|------------|
| **Одиночный бинарник вместо распределённого** | vmsingle вместо Prometheus+оператор, single-node victoria-logs вместо кластера, promtail вместо конвейера агентов. На одном узле любой слой координации — чистый оверхед. |
| **Статический конфиг вместо discovery** | Scrape-таргеты — static_configs, путь к логам — глоб, дашборды и datasources — файлы в git. Механизмы discovery окупают сложность там, где вещи приходят и уходят; здесь не уходит ничего. |
| **hostPath PV + Retain + явный биндинг через volumeName** | Ни storage class, ни провижионера; данные переживают helm uninstall, а `storageClassName: ""` на PVC не даёт ему ждать провижионер, которого нет. |
| **Ограниченная память везде** | У каждого компонента лимиты; vmsingle дополнительно зажимает кэши через `memory.allowedPercent: 20`. На общей ноде безлимитный стек наблюдаемости первым делом OOM-ит те самые сервисы, за которыми должен следить. |
| **Стабильные ClusterIP-имена** | Grafana и vmalert ходят в `vmsingle-stable` — обычный ClusterIP перед headless-сервисом чарта: headless DNS раздаёт IP подов, которые протухают при рестартах CoreDNS. |

## Что может пойти не так
Информация об устранении неполадок, специфичных для vmsingle, см. в [руководстве по vmsingle](../VictoriaMetrics/vmsingle_single_node.md).

### 1. Стек мониторит всё, кроме собственной смерти

Если нода легла, vmalert лёг вместе с ней, и Telegram молчит. Внешняя страховка — алерт Beszel на отвал агента плюс blackbox-пробы публичных сайтов — но blackbox тоже живёт на этой же ноде. Честная детекция мёртвой ноды требует одного зонда снаружи; внешний uptime-чекер, дёргающий `status.antonnovikov.com`, закрывает вопрос.

### 2. Метрики в Grafana есть, logs-панели пустые

Диагноз в три шага:
1. VMUI на `victoria-logs:9428/select/vmui` отдаёт данные (хранилище ок)?
2. Страница `/targets` у Promtail показывает файл активным (доставка ок)?
3. UID datasource в дашборде совпадает с запровижиненным (проводка ок)?

У автора было третье — фиксируйте UID.

### 3. После ребута ноды всё рестартует разом

Девять компонентов, стартующих наперегонки на двух ядрах — liveness-пробы не успевают, и поды рестартуют волнами. Щедрый `initialDelaySeconds` на stateful-подах (vmsingle, victoria-logs, grafana) разрывает петлю; stateless могут потрепыхаться без вреда.

## Итог

- Две базы-бинарника — VictoriaMetrics для метрик (90d) и VictoriaLogs для логов (7d) — закрывают оба сигнала за 160 МБ RAM в requests на двоих
- Полный стек из девяти компонентов запрашивает 452 МБ / 170m CPU и уживается с боевыми сервисами на двухъядерном VPS
- Promtail соединяет два мира: JSON access-логи Traefik → протокол Loki → VictoriaLogs, рядом с метриками в одной Grafana
- Алерты идут vmalert → alertmanager → Telegram; SSL expiry и предсказание заполнения диска — два, которые уже себя окупили
- Везде одни паттерны: одиночный бинарник, статический конфиг, hostPath+Retain, ограниченная память, стабильные имена сервисов
- Оставшаяся дыра — самонаблюдение: нужен зонд вне ноды

## См. также

- [Архитектура наблюдаемости в Kubernetes](./kubernetes-monitoring-logging-architecture.md) — общая схема стека мониторинга
- [Развёртывание VictoriaLogs в Kubernetes](./victorialogs_k8s_setup.md) — детальная инструкция по VictoriaLogs
- [Обзор VictoriaMetrics](../VictoriaMetrics/overview.md) — архитектура, компоненты, сравнение
- [Обзор vmalert](../VictoriaMetrics/vmalert_overview.md) — правила алертинга, интеграция с VictoriaLogs
- [LogsQL: руководство по запросам](../VictoriaMetrics/logsql_overview.md) — синтаксис и функции аналитики логов
- [Grafana provisioning](../Grafana/grafana_provisioning.md) — дашборды и datasources как код