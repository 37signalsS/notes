# Проверки здоровья и откат развертывания

> Этот материал — общий справочник по проверкам здоровья (Health Checks) и процедурам отката (Rollback) в контексте CI/CD и эксплуатации. Детали по отдельным механизмам вынесены в профильные разделы: синтаксис проб Kubernetes — в **[Пробах в Kubernetes](../../Kubernetes/Base/probes.md)**, дизайн HTTP-эндпоинтов здоровья — в **[Health Checks и Readiness (HTTP)](../../Networking/Protocols/HTTP/http_health_checks_readiness.md)**, активные проверки балансировщика — в **[Балансировке нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)**, супервизоры системных служб — в **[systemd](../../Linux/Core/systemd/systemd_unit_file_structure.md)**.

## Определения

**Проверка здоровья (Health Check)** — автоматизированный механизм оценки состояния приложения, используемый оркестраторами, балансировщиками и CI/CD-системами для принятия решения о готовности новой версии к приему трафика или необходимости перезапуска.

- **Откат (Rollback)** — процесс возврата системы к предыдущему стабильному состоянию (версии кода, конфигурации, пакета или схемы данных) при обнаружении аномалий или сбоев после выпуска. Откат должен быть **идемпотентным** — его можно запускать повторно без побочных эффектов.
- **Гейтинг (Gating)** — методология использования Health Checks как «шлюзов» для прогрессивной раскатки (если проверки не пройдены, раскатка блокируется или инициируется откат).
- **Автоматический судья (Judge / Analysis Engine)** — компонент, принимающий решение об откате на основе анализа временных рядов (метрики Prometheus/VictoriaMetrics) или результатов проверок. В облачной среде это Argo Rollouts Analysis / Kayenta; в традиционной (Bare Metal / VM) — скрипт, вызываемый из Ansible/CI, либо внешний webhook от Alertmanager (см. **[Мониторинг Canary релизов](./canary_monitoring_and_gating.md)**).
- **Эндпоинт здоровья (Health Endpoint)** — выделенная HTTP/TCP-точка приложения (например, `GET /healthz`, `/ready`, `/live`), возвращающая `200 OK` при работоспособности и `503` при проблеме. Дизайн и типы эндпоинтов подробно разобраны в профильном разделе про **[HTTP health checks](../../Networking/Protocols/HTTP/http_health_checks_readiness.md)**.
- **Процессный супервизор (Process Supervisor)** — система управления процессами (systemd, supervisord, monit, runit), выполняющая роль «liveness-пробы» вне оркестратора: перезапускает упавший процесс, управляет порядком старта и корректной остановкой.
- **Drain (Вывод из пула / дрейнирование)** — процедура исключения узла/инстанса из балансировки (HAProxy `drain`, Nginx `down`, `kubectl drain`) перед остановкой, чтобы завершить обслуживание текущих соединений без разрыва активных запросов.
- **Симлинк-деплой (Symlink Deployment)** — модель выпуска, при которой релизы раскладываются в изолированные каталоги, а активная версия указывается через симлинк `current`. Откат сводится к атомарной перестановке симлинка — без переустановки пакетов.
- **Expand-Contract (Parallel Change)** — паттерн обратно-совместимых миграций БД, позволяющий откатывать код без поломки схемы данных (сначала расширение схемы, затем контракт, затем очистка). Каноническое описание — в **[Обратно-совместимых миграциях](../../Databases/Concepts/migrations/expand_contract.md)**.

## Основные концепции

### Триада проб (Kubernetes Probes)

В оркестрированных средах (Kubernetes) надёжность релиза базируется на трёх уровнях проверки. Подробный синтаксис и параметры — в **[Пробах в Kubernetes](../../Kubernetes/Base/probes.md)**; общая типология HTTP-проверок — в профильном **[HTTP-разделе](../../Networking/Protocols/HTTP/http_health_checks_readiness.md)**.

1.  **`startupProbe` (Защита при старте):**
    - **Цель:** Изоляция процесса прогрева (Warm-up). Пока эта проба не пройдена, остальные проверки отключены.
    - **Критична** для тяжёлых Java/JVM-приложений с долгим JIT-компилятором (прогрев может занимать десятки секунд и более) и для сервисов с медленной инициализацией кэшей/пулов соединений.
2.  **`readinessProbe` (Управление трафиком):**
    - **Цель:** Определение готовности обслуживать запросы. При сбое экземпляр исключается из балансировки (EndpointSlice).
    - **Важно:** Должна проверять локальную готовность **и** доступность критических зависимостей (БД, кэш, очередь), иначе балансировщик будет слать трафик в «зомби».
3.  **`livenessProbe` (Самоисцеление):**
    - **Цель:** Детекция тупиковых состояний (Deadlocks, OOM). При сбое контейнер перезапускается.
    - **Риск:** Слишком агрессивная liveness-проба может вызвать каскадный перезапуск всех подов при временной деградации БД — поэтому liveness **никогда** не должна зависеть от внешних сервисов.

### Слоистые проверки здоровья (Layered Health Checks)

Надёжность достигается не одной пробой, а их комбинацией на разных уровнях. Каждый слой ловит свои классы отказов; опора на единственный слой даёт ложную уверенность (например, TCP-порт открыт, но приложение зависло).

| Уровень | Механизм | Что ловит | Что НЕ ловит |
| :--- | :--- | :--- | :--- |
| **Супервизор процесса** (systemd/monit) | Перезапуск упавшего процесса | Падение процесса, зависание с потреблением 100% CPU | Логические ошибки, «зомби»-процесс, отвечающий на порт |
| **Эндпоинт приложения** (`/live`, `/ready`) | HTTP/TCP-запрос к сервису | Неготовность, падение зависимостей | Сетевую недоступность узла целиком |
| **Активная проверка LB** (HAProxy `httpchk`, Nginx `health_check`) | Опрос балансировщиком | Узел, не проходящий проверку | Короткие всплески (зависит от `inter`/`rise`/`fall`) |
| **Пассивный мониторинг** (Prometheus: 5xx, latency) | Анализ реального трафика | Регрессии качества, деградацию метрик | Отсутствие трафика (нечего анализировать) |
| **Синтетика / Smoke** (`curl`, `goss`) | Искусственный запрос после шага | Функциональные поломки сразу после деплоя | Продуктовые сценарии под нагрузкой |

> Дизайн самих HTTP-эндпоинтов (`/live` vs `/ready` vs `/startup`, проверка зависимостей) — в **[Health Checks и Readiness (HTTP)](../../Networking/Protocols/HTTP/http_health_checks_readiness.md)**; активные проверки на стороне балансировщика — в **[Балансировке нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)**.

### Архитектура автоматизированного отката

Автоматический откат строится по единой схеме независимо от среды: **сбор данных → анализ (Judge) → действие**.

1.  **В облачной оркестрации (Kubernetes):**
    1.  **Сбор данных:** Агент (Prometheus) собирает Error Rate и Latency.
    2.  **Анализ:** Судья сравнивает метрики новой версии с эталоном (Baseline).
    3.  **Действие:** Если отклонение выше порога (например, рост 5xx на 2%), инициируется `kubectl rollout undo` или переключение весов в Gateway API.
2.  **В традиционной среде (Bare Metal / VM):**
    1.  **Сбор данных:** Health-эндпоинт опрашивается балансировщиком и/или скриптом из CI/Ansible; метрики тянутся из Prometheus.
    2.  **Анализ:** Gate-шаг пайплайна (Bash/Python Judge, см. **[Canary-гейтинг](./canary_monitoring_and_gating.md)**) сравнивает canary и baseline, проверяет синтетику.
    3.  **Действие:** При провале — возврат узла в пул со старой версией (перестановка симлинка / `apt install pkg=<prev>` / включение резервного server в HAProxy) и повторная проверка.

**Принцип Fail-Closed (безопасный отказ):** при недоступности системы мониторинга, отсутствии данных или ошибке самого «судьи» раскатка **останавливается** (и по возможности инициирует откат), а не продолжается автоматически.

### Глубина истории и артефакты

Параметр/практика, определяющая, на сколько шагов назад можно вернуться мгновенно:

- **Kubernetes:** `revisionHistoryLimit` (рекомендация — минимум 5–10 ревизий). При откате поды удаляются, поэтому для анализа причин (RCA) настраивают автоматический сбор дампов (CrashLoopBackOff) и внешнее логирование.
- **Симлинк-деплой:** храните N предыдущих каталогов релизов (например, `releases/2024-05-01T10.00`, `...T10.15`); откат — `ln -sfn` на нужный.
- **Пакетный деплой:** кэшируйте предыдущую версию пакета локально (`apt-cache` / `dnf history`) или в репозитории, чтобы `apt install pkg=<prev>`/`dnf downgrade` работал офлайн.
- **Контейнерный деплой (не-cloud):** сохраняйте предыдущий тег образа в реестре; откат — рестарт контейнера со старым тегом.

**Артефакты RCA:** логи должны уходить во внешнее хранилище (journald → центральный коллектор, либо файлы в смонтированном томе), иначе после отката контейнера/инстанса контекст инцидента теряется.

## Практические сценарии

### 1. Настройка проб для gRPC и HTTP/3 (Kubernetes 1.30+)

Использование нативных механизмов для современных протоколов.

```yaml
spec:
  containers:
  - name: api-service
    image: my-app:v2.4.0
    # gRPC проверка
    readinessProbe:
      grpc:
        port: 9000
      initialDelaySeconds: 5
    # HTTP/3 проверка через exec (если балансировщик не поддерживает L7 пробы)
    livenessProbe:
      exec:
        command: ["/usr/bin/check-quic", "--port", "443"]
      periodSeconds: 10
```

**Валидация:** `kubectl describe pod` показывает `Readiness: gRPC 9000` и `Liveness: exec`; после старта `kubectl get pods` → `READY 1/1`.

### 2. Автоматический Rollback в GitLab CI (Bash + Prometheus)

Сценарий для простых пайплайнов: после деплоя ждём усадки метрик и сравниваем Error Rate с порогом.

```bash
# Проверка Error Rate через 5 минут после деплоя
ERROR_RATE=$(curl -s "http://vm-select:8481/select/0/prometheus/api/v1/query" \
  --data-urlencode 'query=sum(rate(http_errors_total[5m])) / sum(rate(http_requests_total[5m]))' \
  | jq -r '.data.result[0].value[1]')

if (( $(echo "$ERROR_RATE > 0.02" | bc -l) )); then
  echo "CRITICAL: Error rate $ERROR_RATE > 2%. Initiating Rollback..."
  kubectl rollout undo deployment/api-server
  exit 1
fi
```

**Валидация:** при искусственной подаче 5xx `ERROR_RATE` превышает 0.02, пайплайн печатает `CRITICAL` и выполняет `rollout undo`. Для не-k8s среды `kubectl rollout undo` заменяется на перестановку симлинка/пакета (см. сценарии 6–8).

### 3. Использование AnalysisTemplate (Argo Rollouts)

Декларативный гейтинг — общепринятый стандарт для Kubernetes.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate
spec:
  metrics:
  - name: success-rate
    interval: 2m
    successCondition: result[0] >= 0.98
    failureLimit: 3
    provider:
      prometheus:
        address: http://prometheus:9090
        query: |
          sum(rate(http_requests_total{status!~"5.*"}[2m])) 
          / 
          sum(rate(http_requests_total[2m]))
```

**Валидация:** при падении `success-rate` ниже 0.98 трижды подряд (`failureLimit: 3`) Argo Rollouts автоматически останавливает Rollout и откатывает веса.

### 4. Супервизор системной службы (systemd): авто-перезапуск и корректная остановка

Вне Kubernetes роль liveness-пробы играет systemd. Ниже — юнит, который перезапускает зависшее приложение (watchdog) и корректно завершает текущие запросы при остановке (graceful shutdown).

```ini
# /etc/systemd/system/my-service.service
[Unit]
Description=My Service (canary-capable)
After=network.target postgresql.service

[Service]
Type=notify                       # приложение само сигнализирует systemd о готовности через sd_notify
ExecStart=/opt/my-service/bin/app --listen :8080
ExecStartPre=/usr/bin/curl -sf http://localhost:8080/ready || exit 1  # pre-flight health до старта
ExecStop=/bin/kill -TERM $MAINPID
Restart=on-failure               # перезапуск при падении (аналог liveness)
RestartSec=5
WatchdogSec=30                   # systemd убьёт и перезапустит процесс, если тот не продлит watchdog
TimeoutStartSec=60
TimeoutStopSec=30                # время на graceful shutdown перед SIGKILL
User=app
Environment=VERSION=2.4.0

[Install]
WantedBy=multi-user.target
```

Приложение должно:
- при старте вызвать `sd_notify("READY=1")` (библиотеки есть для Go, Python `py systemd`, Java `systemd-notify`);
- периодически продлевать watchdog (`sd_notify("WATCHDOG=1")`);
- при `SIGTERM` завершить активные запросы в пределах `TimeoutStopSec`, затем выйти.

**Валидация:**
```bash
systemctl daemon-reload
systemctl start my-service
systemctl is-active my-service   # → active
journalctl -u my-service -f      # логи; при зависании > WatchdogSec процесс будет перезапущен
```
Полный разбор юнитов и `sd_notify` — в **[структуре юнитов systemd](../../Linux/Core/systemd/systemd_unit_file_structure.md)** и **[практике systemd](../../Linux/Core/systemd/systemd_practical_scenarios.md)**.

### 5. Активная проверка и откат на уровне HAProxy

Балансировщик сам исключает нездоровые узлы и может стать точкой отката: старую версию не удаляем, а держим вторым `server`, управляя им через runtime-сокет.

```haproxy
# haproxy.cfg
frontend http_frontend
    bind *:80
    default_backend app_backend

backend app_backend
    balance leastconn
    # Активная HTTP-проверка готовности (аналог readiness-пробы)
    option httpchk GET /ready
    http-check expect status 200
    server app_v2_1 10.0.1.20:8080 check inter 3s rise 2 fall 3
    # Резервный server со СТАРОЙ версией — для мгновенного отката
    server app_v1_1 10.0.1.21:8080 check inter 3s rise 2 fall 3 backup
```

Управление узлами без перезагрузки HAProxy (через stats-сокет):

```bash
# Вывести новую версию из пула (drain) перед деплоем
echo "drain app_backend/app_v2_1" | socat stdio /var/run/haproxy.sock
# После деплоя и проверки — вернуть в ротацию
echo "enable server app_backend/app_v2_1" | socat stdio /var/run/haproxy.sock
# ОТКАТ: вывести новую версию, поднять старую (backup -> active)
echo "disable server app_backend/app_v2_1" | socat stdio /var/run/haproxy.sock
echo "enable  server app_backend/app_v1_1" | socat stdio /var/run/haproxy.sock
# Проверить состояние
echo "show servers state" | socat stdio /var/run/haproxy.sock
```

**Валидация:** `show servers state` показывает `app_v2_1` в статусе `MAINT`/`no check`, а `app_v1_1` — `UP`; трафик уходит на старую версию. Активные проверки и `inter/rise/fall` подробнее в **[Балансировке нагрузки HTTP](../../Networking/Protocols/HTTP/http_load_balancing.md)**.

### 6. Атомарный деплой и мгновенный откат через симлинк

Модель Capistrano-style: релизы не перезаписывают друг друга, активная версия — симлинк. Откат не требует переустановки.

```bash
# Структура
# /opt/myapp/
#   releases/2024-05-01T10.00/   <- старая версия
#   releases/2024-05-01T10.15/   <- новая версия
#   current -> releases/2024-05-01T10.15

DEPLOY_ROOT=/opt/myapp
RELEASE=$(date +%Y-%m-%dT%H.%M)
mkdir -p "$DEPLOY_ROOT/releases/$RELEASE"
cp -r ./dist/* "$DEPLOY_ROOT/releases/$RELEASE/"

# Атомарная перестановка симлинка (нет разрыва на полпути)
ln -sfn "$DEPLOY_ROOT/releases/$RELEASE" "$DEPLOY_ROOT/current"

# Перезапуск супервизора (systemd/supervisord) — подхватывает новый current
systemctl restart my-service

# --- ОТКАТ ---
PREV=$(ls -1t "$DEPLOY_ROOT/releases" | sed -n '2p')   # предыдущий релиз
ln -sfn "$DEPLOY_ROOT/releases/$PREV" "$DEPLOY_ROOT/current"
systemctl restart my-service
readlink -f "$DEPLOY_ROOT/current"   # → должен указывать на $PREV
```

**Валидация:** после отката `readlink -f current` указывает на предыдущий каталог, `curl -s localhost:8080/version` возвращает старую версию, `systemctl is-active my-service` — `active`.

### 7. Gate-шаг и откат в Ansible

Плейбук, который деплоит новую версию, затем проверяет здоровье и при провале автоматически возвращает предыдущий симлинк + перезагружает балансировщик. Полный пример для традиционной инфраструктуры — в **[Традиционной инфраструктуре](./traditional_infrastructure.md)**.

```yaml
# rollback_gate.yml (фрагмент)
- hosts: app_servers
  vars:
    deploy_root: /opt/myapp
    prev_release: "{{ lookup('pipe','ls -1t ' + deploy_root + '/releases | sed -n 2p') }}"
  tasks:
    - name: Переставить симлинк на новый релиз
      file:
        src: "{{ deploy_root }}/releases/{{ new_release }}"
        dest: "{{ deploy_root }}/current"
        state: link
      notify: restart my-service

    - name: Health check после деплоя
      uri:
        url: http://localhost:8080/ready
        status_code: 200
      register: hc
      retries: 10
      delay: 3
      until: hc.status == 200

  handlers:
    - name: restart my-service
      systemd:
        name: my-service
        state: restarted

  # При провале health check (блок rescue) — откат симлинка
  block:
    - assert: { that: "hc.status == 200", fail_msg: "Health check failed" }
  rescue:
    - name: Вернуть предыдущий релиз
      file:
        src: "{{ deploy_root }}/releases/{{ prev_release }}"
        dest: "{{ deploy_root }}/current"
        state: link
      notify: restart my-service
    - name: Сообщить об откате
      debug: { msg: "ROLLBACK to {{ prev_release }}" }
```

**Валидация:** при недоступном `/ready` плейбук падает в `rescue`, симлинк возвращается к `prev_release`, служба перезапускается; в логах Ansible видно `ROLLBACK to ...`.

### 8. Пакетный откат (apt / dnf) с возвратом конфигурации

Для деплоев через системный пакет откат — установка предыдущей версии пакета. Критично: конфиги тоже нужно откатывать, иначе новый конфиг сломает старый код.

```bash
# Debian/Ubuntu: откат к известной версии (версия кэшируется локально)
apt-get install -y myapp=2.3.1-1   # → stdout: "Настроен пакет myapp"
# если conffiles конфликтуют — явно вернуть предыдущий конфиг из управления конфигурациями
ansible-playbook deploy.yml --tags config   # возвращает шаблоны под 2.3.1

# RHEL/Fedora: откат через историю транзакций
dnf history list
dnf history undo <ID>   # отменяет транзакцию установки новой версии
```

**Валидация:** `dpkg -l myapp | grep ^ii` (или `rpm -q myapp`) показывает старую версию; `systemctl is-active my-app` — `active`; smoke-тест `/ready` возвращает `200`. Управление конфигурациями (Ansible/Chef) должно быть частью отката, чтобы избежать рассинхрона «код/конфиг».

## Операции и команды

### Проверка здоровья: HTTP/TCP/CLI

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **HTTP healthz** | `curl -sf http://localhost:8080/healthz` | Возвращает `200 OK` или падает с ненулевым кодом. |
| **TCP port check** | `nc -zv 10.0.1.20 8080 </dev/null 2>&1` | `Connection succeeded` или `Connection refused`. |
| **systemd status** | `systemctl is-active --quiet my-service && echo "OK"` | `OK` или ненулевой exit code. |
| **Journal tail** | `journalctl -u my-service -n 50 --no-pager` | Последние 50 строк логов сервиса. |
| **Process alive** | `pgrep -f "my-app" > /dev/null && echo "running"` | `running` или ненулевой exit code. |

### systemd: управление службой и watchdog

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Reload юнита** | `systemctl daemon-reload` | Перечитывает `/etc/systemd/system/*.service`. |
| **Restart** | `systemctl restart my-service` | Корректный restart через `ExecStop`/`ExecStart`. |
| **Watchdog статус** | `systemctl show my-service -p WatchdogTimestamp` | Время последнего продления watchdog. |
| **Fail-count** | `systemctl show my-service -p NRestarts` | Число перезапусков за время загрузки юнита. |
| **Откат юнита** | `systemctl revert my-service` | Возвращает юнит к vendor-версии (если изменялся). |

### HAProxy: drain, enable, disable, stat

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Drain сервер** | `echo "drain app_backend/app_v2_1" \| socat stdio /var/run/haproxy.sock` | Сервер переходит в `MAINT`; текущие соединения завершаются. |
| **Вернуть в ротацию** | `echo "enable server app_backend/app_v2_1" \| socat stdio /var/run/haproxy.sock` | Сервер снова получает трафик. |
| **Выключить сервер** | `echo "disable server app_backend/app_v2_1" \| socat stdio /var/run/haproxy.sock` | Сервер исключается из пула без drain. |
| **Текущее состояние** | `echo "show servers state" \| socat stdio /var/run/haproxy.sock \| grep app_v2_1` | Выводит строку таблицы серверов с весами и статусами. |

### Nginx: проверка конфигурации и reload

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Проверка синтаксиса** | `nginx -t` | `test is successful` или ошибка с номером строки. |
| **Graceful reload** | `nginx -s reload` | Перезагрузка конфига без разрыва соединений. |
| **Версия** | `nginx -v 2>&1 \| awk -F/ '{print $2}'` | Выводит версию бинарника. |

### Симлинк-деплой: откат и верификация

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Текущий релиз** | `readlink -f /opt/myapp/current` | Абсолютный путь к активному релизу. |
| **Атомарный откат** | `ln -sfn /opt/myapp/releases/2024-05-01T10.00 /opt/myapp/current` | Симлинк переключается мгновенно. |
| **Список релизов** | `ls -1t /opt/myapp/releases \| head` | Новые релизы сверху; для отката берётся второй. |
| **Верификация** | `curl -s http://localhost:8080/version` | Возвращает версию активного релиза. |

### Пакетный менеджер: откат и история

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **История apt** | `grep "install " /var/log/dpkg.log \| tail` | Последние установки пакетов. |
| **Откат apt** | `apt-get install -y myapp=2.3.1-1` | Устанавливает указанную версию. |
| **История dnf** | `dnf history list` | Список транзакций с ID. |
| **Откат dnf** | `dnf history undo <ID>` | Отменяет транзакцию по ID. |
| **Версия пакета** | `dpkg -l myapp \| grep ^ii` / `rpm -q myapp` | Текущая установленная версия. |

### Prometheus: запросы для health/rollback валидации

| Действие | PromQL / Команда | Результат |
| :--- | :--- | :--- |
| **Error rate** | `sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))` | Доля 5xx за последние 5 минут. |
| **Availability** | `sum(rate(http_requests_total{status!~"5.."}[5m])) / sum(rate(http_requests_total[5m]))` | Доступность сервиса (0–1). |
| **Ревизии K8s** | `kubectl rollout history deployment/api-server` | Список ревизий для ручного отката. |
| **Откат K8s** | `kubectl rollout undo deployment/api-server --to-revision=3` | Откат к указанной ревизии. |

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Циклический рестарт (Liveness Flapping)** | Слишком короткий таймаут пробы при высокой нагрузке. | Увеличить `timeoutSeconds` или `failureThreshold`. В systemd — поднять `WatchdogSec`/`RestartSec` и проверить, что приложение ловит `SIGTERM`. |
| **Трафик на «зомби»-инстансы** | Приложение зависло, но readiness/TCP-проверка ещё «зелёная» (порт открыт). | Углубить проверку: HTTP `httpchk` на `/ready` с проверкой зависимостей, а не только TCP-порт. В Kubernetes — уменьшить `periodSeconds` readiness и внедрить Circuit Breaker на клиенте. |
| **Откат невозможен (K8s)** | `revisionHistoryLimit` установлен в 0 или 1. | Увеличить лимит истории в манифесте Deployment. |
| **Откат БД сломал код** | Откат кода (Rollback) произошёл без отката схемы данных. | Использовать паттерн **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)** для обеспечения совместимости. Глубокие стратегии отката состояния — в **[Стратегиях отката данных](../../Databases/Concepts/rollback_strategies.md)**. |
| **Stuck Rollout** | Новая версия не проходит `startupProbe`. | Проверить логи `kubectl logs --previous` и ресурсы (CPU/RAM). |
| **Супервизор в петле рестартов (systemd loop)** | `RestartSec` мал, или приложение падает при получении `SIGTERM`. | Поднять `RestartSec`; убедиться, что код корректно обрабатывает `SIGTERM` и успевает завершиться до `TimeoutStopSec`; смотреть `journalctl -u my-service -f`. |
| **Откат симлинком не сработал** | Забыли перезапустить супервизор либо LB ещё указывает на старый сокет/порт. | `readlink -f current` (должен указывать на нужный релиз), `systemctl restart my-service`, перезагрузить/дрейнировать балансировщик. |
| **Пакетный откат сломал конфиг** | `conffiles` изменились между версиями. | Откатывать конфигурацию вместе с пакетом через систему управления конфигурациями (Ansible/Chef), а не только `apt/dnf`. |
| **Drain застрял (HAProxy socket недоступен)** | Сокет не создан или нет прав. | Проверить `ls -l /var/run/haproxy.sock`; в `global` HAProxy прописать `stats socket /var/run/haproxy.sock mode 660 level admin`. |
| **Ложноположительный 200** | Health-эндпоинт проверяет только «процесс жив», игнорируя БД/кэш. | Добавить в `/ready` реальные проверки зависимостей (см. **[HTTP health checks](../../Networking/Protocols/HTTP/http_health_checks_readiness.md)**). |
| **Rollback завис на половине** | Откат прерван (остановлен systemd, разорван SSH). | Повторить откат — он идемпотентен; убедиться, что symlink/pack/образа не повредились. |
| **Частичный откат (не все узлы)** | Скрипт отката упал на половине батча; часть узлов осталась на новой версии. | Внести остальные узлы в инвентарь отката и повторить; использовать Ansible `serial` + `rescue` для атомарности. |

## Лучшие практики

1.  **Graceful Shutdown:** При получении `SIGTERM` (начало отката или обновления) приложение должно завершить текущие запросы. Используйте `terminationGracePeriodSeconds` (K8s, минимум 30–60с) или `TimeoutStopSec` (systemd); на стороне балансировщика — предварительный `drain`.
2.  **Разделение зависимостей:** `readinessProbe` может проверять БД, но `livenessProbe` (и systemd watchdog) — **никогда**. Иначе падение БД приведёт к рестарту всего прикладного слоя (каскадная авария).
3.  **In-Place Resize:** При обновлении лимитов ресурсов через VPA/HPA (без перезапуска пода) пробы продолжают работать. Убедитесь, что таймауты проб учитывают возможные задержки при изменении CPU.
4.  **Глубина health-проверки:** Эндпоинт должен проверять критичные зависимости (БД, кэш, очередь), а не только факт «процесс жив» — иначе балансировщик пускает трафик в «зомби». Дизайн эндпоинтов — в **[HTTP health checks](../../Networking/Protocols/HTTP/http_health_checks_readiness.md)**.
5.  **Idempotent rollback:** Откат должен быть повторно запускаемым. Всегда сохраняйте предыдущий артефакт (симлинк на релиз, дайджест образа, закэшированный пакет, `revisionHistoryLimit`).
6.  **Петля верификации после отката:** После возврата версии обязателен повторный health-check и smoke-тест, прежде чем объявить инцидент закрытым.
7.  **Согласование таймаутов:** Интервал опроса балансировщика > время корректной остановки приложения; `TimeoutStopSec`/`terminationGracePeriodSeconds` > реальное время завершения запросов; `WatchdogSec` > период продления watchdog в коде.
8.  **Дисциплина отката данных:** Код и схема БД откатываются согласованно через **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**; никогда не откатывайте только код, оставляя новую миграцию — это ломает старую версию. Подробнее про откат стейтфул-слоя — в **[Стратегиях отката данных](../../Databases/Concepts/rollback_strategies.md)**.
9.  **Тестирование отката:** Процедуру возврата проверяйте не реже, чем сам деплой. Регулярно выполняйте откат в staging, чтобы убедиться в идемпотентности и скорости.
10. **Разделение мониторинга здоровья и продуктовых метрик:** Health Check отвечает на вопрос «жив ли процесс?», а мониторинг — «работает ли продукт?». Не смешивайте эти каналы: ошибка в `/ready` не должна зависеть от внешнего API, а деградация метрик не должна перезапускать процесс без анализа.

## Граничные случаи и ограничения

- **Откат без отката схемы БД.** Если новая версия уже применила миграцию, старый код не сможет работать со старой схемой. Expand-Contract mitigates это, но требует дисциплины.
- **Частичный откат при распределённом деплое.** При откате только части инстансов возможна ситуация, когда клиенты видят разные версии одновременно. Необходима синхронизация через балансировщик или service mesh.
- **Health check на разделяемых ресурсах.** Если `/ready` проверяет общую очередь или кэш, всплеск трафика на другой сервис может ложноположительно помешать health check текущего приложения.
- **Clock skew при проверке временных меток.** Если время на узле отстаёт/опережает на > scrape interval, пассивный мониторинг (Prometheus) даёт сдвинутые временные ряды. Всегда синхронизируйте время через `chrony` и проверяйте `ntpq -p` перед деплоем.
- **Rollback во время миграции данных.** Длинные миграции (например, переиндексация больших таблиц) могут не успеть завершиться до отката. Планируйте обратимые миграции или используйте двойную запись (dual write).
- **Каскадный откат (thundering herd).** При массовом падении новой версии автоматический откат всех инстансов одновременно создаёт всплеск на старую версию. Используйте батчевый откат (`serial` в Ansible) или постепенный drain.
- **Откат конфигурации отдельно от кода.** Если конфиг откачен, а код — нет (или наоборот), возможна несовместимость. Управляйте кодом и конфигом как единым артефактом (monorepo, immutable image, или синхронизированный Ansible плейбук).
- **StatefulSet откат в Kubernetes.** Откат StatefulSet не всегда атомарен: первичный узел может откатиться, а вторичные остаться на новой версии. Требуется дополнительная проверка `ReplicaSet`'ов и версии pod'ов.

## Дополнительная информация

### Рекомендованные ссылки

- **[Пробы в Kubernetes — детали](../../Kubernetes/Base/probes.md)** — техническая реализация и синтаксис.
- **[Мониторинг Canary релизов](./canary_monitoring_and_gating.md)** — глубокий анализ метрик и автооткат (Judge).
- **[Обратно-совместимые миграции](../../Databases/Concepts/migrations/expand_contract.md)** — как выжить при откате приложения.
