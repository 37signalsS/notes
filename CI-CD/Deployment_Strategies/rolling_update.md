# Rolling Update — поэтапное обновление

> Стратегия развертывания, при которой экземпляры приложения заменяются поочередно или небольшими группами (батчами), обеспечивая непрерывную доступность сервиса. Ниже описаны как облачные реализации (Kubernetes, Docker Swarm — сохранены для полноты), так и трек традиционной инфраструктуры (Bare Metal / VM) через Nginx, HAProxy, systemd, Ansible и rsync — без использования облачных сервисов.

## Определения

**Rolling Update (Поэтапное обновление)** — стратегия развертывания (**Deployment**), при которой экземпляры приложения (**Pods**, виртуальные машины, контейнеры) обновляются поочередно или небольшими группами. Новая версия постепенно заменяет старую, обеспечивая непрерывную доступность сервиса.

- **Нулевое время простоя (Zero Downtime)** — ключевая цель стратегии, достигаемая за счет того, что часть экземпляров всегда остается в рабочем состоянии и готова принимать трафик через балансировщик.
- **Радиус поражения (Blast Radius)** — при Rolling Update радиус поражения ограничен количеством одновременно обновляемых подов (контролируется `maxUnavailable`).
- **Ревизия (Revision)** — сохраненное состояние манифеста, позволяющее выполнить откат.
- **Пакетная раскатка (Batch / Wave / Serial)** — обновление группы хостов (батча) с проверкой здоровья и паузой между волнами. Аналог `serial` в Ansible или `maxUnavailable`/`maxSurge` в Kubernetes, но применительно к физическим/виртуальным серверам.
- **Вывод из пула (Drain)** — процесс отключения узла от балансировщика (перевод в режим `drain`/`maintenance`) перед обновлением, чтобы он перестал принимать новые соединения (Connection Draining), при этом текущие запросы доживаются.
- **Бережное завершение (Graceful Shutdown)** — корректное завершение процесса: перехват `SIGTERM`, отказ от новых запросов, ожидание завершения активных (обычно 10–60 с) и только затем выход. Критично для отсутствия 502/504 при Rolling Update.
- **Проверка готовности (Health Check / Readiness)** — активная (балансировщик опрашивает `/healthz`) или пассивная (анализ 5xx/таймаутов) проверка того, что экземпляр готов принимать трафик. В традиционной среде реализуется через `option httpchk` в HAProxy или `health_check` в Nginx Plus; в Kubernetes — `readinessProbe`.

## Основные концепции

### Механизм работы в Kubernetes

На уровне Kubernetes Rolling Update управляется контроллером Deployment, который манипулирует объектами **ReplicaSet**:
1.  **Создание нового RS:** При изменении шаблона пода (`spec.template`) создается новый ReplicaSet (v2).
2.  **Поэтапное масштабирование:** Контроллер увеличивает количество реплик в RS v2 и одновременно уменьшает в RS v1, соблюдая ограничения `maxSurge` и `maxUnavailable`.
3.  **Проверка готовности:** Удаление пода из старого RS происходит только после того, как новый под из RS v2 успешно прошел **Readiness Probe**.

### Механизм работы в традиционной инфраструктуре (Bare Metal / VM)

Вне оркестратора та же идея реализуется через балансировщик (HAProxy/Nginx) и поочередный вывод узлов из пула. В любой момент времени ≥1 реплика старой версии остается в строю:

```text
Этап 1:  [v1] [v1] [v1] [v1]   (все узлы в пуле LB, принимают трафик)
Этап 2:  [--] [v1] [v1] [v1]   (app1 выведен в drain, обновляется)
Этап 3:  [v2] [v1] [v1] [v1]   (app1 прошел health, возвращён в пул)
Этап 4:  [v2] [--] [v1] [v1]   (app2 в drain, обновляется)
Этап 5:  [v2] [v2] [--] [v1]
Этап 6:  [v2] [v2] [v2] [--]
Этап 7:  [v2] [v2] [v2] [v2]   (готово, сервис недоступен не был)
```

**Необходимые компоненты в on-prem среде:**
1.  **Балансировщик** (HAProxy / Nginx) с health checks и возможностью вывода узла из пула (`drain`/`state drain`).
2.  **Механизм доставки артефакта** (rsync / Ansible / Packer) и атомарной смены версии (symlink).
3.  **Health-эндпоинт**, реально проверяющий зависимости (БД, кэш), а не только факт запуска процесса.
4.  **Graceful shutdown** в самом приложении (перехват `SIGTERM` + дождаться активных запросов).

### Параметры управления в Kubernetes

| Параметр | Описание | Рекомендация (2026) |
| :--- | :--- | :--- |
| **`maxUnavailable`** | Макс. кол-во подов, недоступных при обновлении. | `0` для критических систем (сначала создать, потом удалить). |
| **`maxSurge`** | Макс. кол-во подов сверх `replicas`. | `25%` или `1-2` для средних нагрузок. |
| **`minReadySeconds`** | Время ожидания после `Ready`, перед тем как под считается рабочим. | `10-30s` для прогрева кэшей и JIT-компиляции. |
| **`progressDeadlineSeconds`** | Время ожидания прогресса до признания обновления зависшим. | `600` (10 минут) — стандарт для детекции сбоев. |
| **`revisionHistoryLimit`** | Кол-во старых ReplicaSet для отката. | `10` — оптимально для глубины истории. |

> **Аналоги в традиционной среде:** `maxUnavailable` ≈ размер батча, выводимого из пула за раз (`serial: 1` в Ansible); `maxSurge` ≈ наличие резервного «N+1» узла, принимающего трафик во время обновления соседей; `minReadySeconds` ≈ пауза/ожидание прогрева после возврата узла в пул.

### Золотые сигналы (Golden Signals) при обновлении

При мониторинге Rolling Update критически важно отслеживать:
- **Errors (Ошибки):** Всплеск 5xx ошибок в момент ротации подов сигнализирует о проблемах в новой версии или некорректном Graceful Shutdown.
- **Latency (Задержки):** Рост времени ответа на новых подах может указывать на отсутствие прогрева кэшей.
- **Traffic (Трафик):** Неравномерное распределение нагрузки между v1 и v2 при использовании Sticky Sessions.
- **Saturation (Насыщенность):** Использование CPU/RAM на узлах, особенно во время `maxSurge`, когда одновременно работают обе версии.

**Конкретные команды мониторинга (вне облака):**
```bash
# HAProxy: статус бэкендов и ошибки через UNIX-сокет
echo "show stat" | socat - UNIX-CONNECT:/var/run/haproxy.sock | cut -d, -f1,2,18,35,36
# → колонки: pxname,svname,status,req.tot,eresp (eresp≠0 — растут ошибки)

# Nginx: экспортер метрик или stub_status
curl -s http://localhost:9113/metrics | grep -E "nginx_upstream|http_requests_total"

# Ручная проверка задержки/кода на конкретном узле
curl -s -o /dev/null -w "%{http_code} %{time_total}\n" http://app1:8080/healthz
# → 200 0.012
```

### Rolling Update vs In-Place Resize (Контекст 2026)

В 2026 году для ресурсоемких приложений (Java, ML) часто используется **In-Place Pod Vertical Scaling**.
- **Rolling Update:** Всегда пересоздает под (новый IP, пустые кэши).
- **In-Place Resize:** Обновляет ресурсы (CPU/RAM) работающего контейнера без перезапуска.
**Вывод:** Rolling Update остается единственным способом обновления *кода* или *конфигурации*, в то время как In-Place Resize предпочтителен для изменения лимитов ресурсов.

*Аналог в традиционной среде:* в systemd (cgroup v2) лимиты можно изменить на живом процессе без рестарта через `systemctl set-property myapp.service MemoryMax=2G CPUQuota=150%` — тот же эффект для долго стартующих приложений.

## Практические сценарии

### Продвинутый Kubernetes Deployment

Пример с использованием контрольных сумм конфигурации (автоматический триггер обновления) и тонкой настройки ресурсов.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-api
spec:
  replicas: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0 # Гарантируем отсутствие потери мощности
  template:
    metadata:
      annotations:
        # Автоматический перезапуск при изменении ConfigMap (стандарт Helm/Kustomize)
        checksum/config: ${CONFIG_CHECKSUM}
    spec:
      terminationGracePeriodSeconds: 60 # Время на завершение транзакций
      containers:
      - name: app
        image: my-repo/app:v2.1.0
        ports:
        - containerPort: 8080
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 15
          periodSeconds: 5
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
```

### Rolling Update в StatefulSet (Partitioning)

В отличие от Deployment, StatefulSet обновляет поды в обратном порядке индексов (от N-1 до 0). Параметр `partition` позволяет реализовать Canary-стиль внутри Rolling Update.

```yaml
spec:
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 3 # Обновятся только поды с индексом >= 3
```

### Docker Swarm: Надежная раскатка

Настройка автоматического отката при сбое и контроля здоровья.

```yaml
services:
  worker:
    image: worker:latest
    deploy:
      replicas: 8
      update_config:
        parallelism: 2
        delay: 20s
        order: start-first     # Сначала поднять новый, потом гасить старый
        failure_action: rollback # АВТО-ОТКАТ при сбое healthcheck
        monitor: 30s           # Сколько следить за здоровьем после старта
        max_failure_ratio: 0.2 # Допустимый процент сбоев
```

### Rolling Update через обратный прокси (Nginx / HAProxy) — традиционная среда

Ключевой примитив on-prem Rolling — вывод узла из пула (drain), обновление, проверка, возврат. Ниже конфигурация HAProxy (open source) и скрипт поэтапной раскатки.

**Конфигурация HAProxy с health check:**
```haproxy
backend app_servers
    balance roundrobin
    option httpchk GET /healthz
    http-check expect status 200
    server app1 10.0.1.10:8080 check inter 3s rise 2 fall 3
    server app2 10.0.1.11:8080 check inter 3s rise 2 fall 3
    server app3 10.0.1.12:8080 check inter 3s rise 2 fall 3
    server app4 10.0.1.13:8080 check inter 3s rise 2 fall 3
```

**Поэтапная раскатка (drain → update → health → enable):**
```bash
HOSTS="app1 app2 app3 app4"
for h in $HOSTS; do
  # 1. Вывести из пула (drain) через UNIX-сокет HAProxy
  echo "set server app_servers/$h state drain" | socat - UNIX-CONNECT:/var/run/haproxy.sock
  # 2. Дождаться завершения активных соединений
  sleep 20
  # 3. Обновить артефакт и перезапустить сервис
  ssh "$h" 'ln -sfn /opt/app/2.4.0 /opt/app/current && systemctl restart myapp'
  # 4. Дождаться готовности
  until curl -sf "http://$h:8080/healthz"; do sleep 3; done
  # 5. Вернуть узел в пул
  echo "set server app_servers/$h state ready" | socat - UNIX-CONNECT:/var/run/haproxy.sock
  # 6. Пауза между волнами для наблюдения за Golden Signals
  sleep 30
done
```

**Валидация:**
```bash
# → все узлы в пуле и UP
echo "show stat" | socat - UNIX-CONNECT:/var/run/haproxy.sock | grep app_servers
# → app1,app_servers,UP,...
```

Аналогичный паттерн через docker-compose с healthcheck описан в материале по стратегиям развертывания: **[Стратегии и модели развертывания](../Core_Concepts/deployment_strategies.md)**.

### Rolling Update через systemd + symlink (атомарная смена версии)

Для монолитов и приложений без балансировщика атомарная смена версии достигается через versioned-каталог и symlink:

```bash
# Атомарная смена версии на хосте (мгновенный откат — переключение symlink обратно)
ln -sfn /opt/app/2.4.0 /opt/app/current
systemctl restart myapp

# Проверка
systemctl is-active myapp   # → active
curl -sf http://localhost:8080/healthz   # → OK
readlink /opt/app/current   # → /opt/app/2.4.0
```

**Rolling внутри одного хоста (несколько инстансов):** запускают v1 на `:8080` и v2 на `:8081` за локальным Nginx, сдвигают вес (`weight`) с v1 на v2, затем останавливают `:8080`. Это дает zero-downtime обновление без второго физического сервера.

Минимальный systemd-юнит с бережным завершением:
```ini
[Service]
Type=notify
ExecStart=/opt/app/current/bin/myapp
WorkingDirectory=/opt/app/current
TimeoutStartSec=60
TimeoutStopSec=30
Restart=on-failure
KillSignal=SIGTERM
# Живой лимит ресурсов (аналог In-Place Resize) без рестарта:
# systemctl set-property myapp.service MemoryMax=2G CPUQuota=150%
```

### Rolling Update через Ansible (Bare Metal / VM)

Ansible реализует батч-раскатку через `serial` и `max_fail_percentage`. Ниже — сокращенный паттерн; полный вариант с `block`/`rescue` автооткатом — в SSoT: **[Стратегии деплоя и rolling updates в Ansible](../../Ansible/ansible_deployment_strategies.md)**.

```yaml
---
- name: Rolling Update (Bare Metal)
  hosts: webservers
  serial: 1                 # по одному хосту (батч)
  max_fail_percentage: 0    # остановить при любой ошибке
  tasks:
    - name: Drain (вывод из балансировщика)
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/disable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost
      ignore_errors: true

    - name: Обновление артефакта
      ansible.builtin.apt:
        name: myapp
        state: latest
      # альтернативы: ansible.builtin.copy или модуль synchronize (rsync)

    - name: Перезапуск
      ansible.builtin.service:
        name: myapp
        state: restarted

    - name: Health check
      ansible.builtin.uri:
        url: "http://{{ ansible_host }}/healthz"
        status_code: 200
      register: h
      retries: 10
      delay: 5
      until: h.status == 200

    - name: Вернуть в пул
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/enable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost
      when: h.status == 200
```

### Распространение артефактов через rsync

Для доставки бинарника/каталога на узлы перед рестартом используют инкрементальную синхронизацию (быстрая для мелких патчей):

```bash
# Инкрементальная доставка новой версии на хост (xxh3 + zstd для скорости)
rsync -av --checksum-choice=xxh3 --compress-choice=zstd \
  deploy@repo:/opt/app/2.4.0/ /opt/app/2.4.0/
systemctl restart myapp
```

Детали флагов, `--link-dest` для истории и ограничений безопасности — в SSoT: **[rsync — синхронизация файлов](../../Linux/SystemAdministration/rsync.md)**.

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Rollout застрял (Stuck)** | Новые поды в `CrashLoopBackOff` или `Pending`. | Проверить `kubectl describe pod` и лимиты ресурсов. |
| **Ошибки 502/504 при деплое** | Короткий `terminationGracePeriod` или отсутствие обработки `SIGTERM`. | Увеличить время завершения и настроить перехват сигналов в приложении. |
| **Трафик на неготовую версию** | Отсутствие или неверная `readinessProbe`. | Настроить пробу, реально проверяющую готовность бизнес-логики. |
| **ImagePullBackOff** | Ошибка авторизации в Registry или опечатка в теге. | Проверить `imagePullSecrets` и существование образа. |
| **Нехватка ресурсов (Surge)** | `maxSurge` требует больше CPU/RAM, чем есть на нодах. | Уменьшить `maxSurge` или использовать `maxUnavailable: 25%`. |
| **Узел не возвращается в пул (drain stuck)** | HAProxy-сокет недоступен или API балансировщика недоступен. | Проверить `ls -l /var/run/haproxy.sock` и права; убедиться, что health-check зеленый. |
| **Частичная передача rsync (exit 23/24)** | Нет места на диске или файлы исчезли в процессе. | Проверить `df -h`; повторить `rsync -av --partial`. |
| **Старая версия продолжает отдавать трафик** | Symlink не переключен или systemd не перечитал бинарь. | Проверить `readlink /opt/app/current`; использовать `restart`, а не `reload`. |
| **Config Drift (расхождение конфигов)** | Ручные правки на серверах. | Ежедневный `ansible-playbook --check --diff`; переход на immutable-образы. |
| **Clock Drift ломает TLS/лидерство** | Уплывание времени между узлами. | `chronyc tracking`; обязательна синхронизация времени перед раскаткой. |
| **Sticky Session рвет активные запросы** | Вывод узла из пула обрывает привязанную сессию. | Внешний session store (Redis) или корректный `drain` с ожиданием. |

## Дополнительная информация

### Лучшие практики

1. **Иммутабельность:** Никогда не используйте тег `:latest`. Обновление должно инициироваться сменой конкретной версии образа или хеша конфигурации.
2. **Expand and Contract:** При обновлении работают две версии приложения. База данных должна поддерживать обе схемы одновременно. Подробнее: **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**.
3. **PDB (Pod Disruption Budget):** Не ограничивает Rolling Update напрямую, но важен для стабильности при одновременных работах на узлах. Подробнее: **[Pod Disruption Budget](../../Kubernetes/Autoscaling/pod_disruption_budget.md)**.
4. **Волновая раскатка (Wave / Progressive):** Делите узлы на волны (10% → 25% → 50% → 100%) с паузой и проверкой Golden Signals между ними. Это превращает Rolling в Progressive Delivery даже без Kubernetes.
5. **Атомарность артефакта:** Используйте versioned-каталоги + symlink (`/opt/app/current`) или immut-образы, чтобы откат был мгновенным (`ln -sfn` на предыдущую версию).

### SRE-практики при Rolling Update

- **Окно наблюдения за волной:** После каждой волны фиксируются Error Rate, P95 Latency и Saturation. Продолжение раскатки допустимо, только если Error Budget не исчерпан (burn rate < порога). При превышении — остановка и откат волны.
- **Автоматический откат (Auto-Rollback):** На традиционной среде это gate-шаг в Ansible/CI: если health-check не прошел или метрики Prometheus превысили SLO — возврат узла в пул со старой версией (смена symlink / `apt install myapp=<prev>`).
- **MTTR:** Короткие обратимые шаги + готовый план отката (смена симлинка / тег образа / `kubectl rollout undo` / возврат узла в пул) снижают время восстановления. Подробнее про проверки здоровья и процедуры отката: **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)**.
- **Связь с DORA:** Rolling с health-проверками и автооткатом улучшает Change Failure Rate и Time to Restore.

### Граничные случаи и ограничения

- **Долгие транзакции/соединения:** `terminationGracePeriodSeconds` (K8s) или `sleep` в drain-процедуре должны покрывать максимальную длительность запроса, иначе — обрыв активных соединений.
- **Session Affinity:** Вывод узла из пула может оборвать sticky-сессию пользователя; решение — внешний session store или корректный drain с ожиданием завершения.
- **Config Drift на Bare Metal:** Серверы «стареют» после ручных правок; без immutable-образов неизбежны расхождения между узлами в одном батче.
- **Нехватка ресурсов для surge:** В традиционной среде `maxSurge` = наличие свободного N+1 узла; при его отсутствии Rolling временно снижает ёмкость (аналог `maxUnavailable > 0`).
- **DNS TTL:** Если балансировка идет через DNS, клиенты могут кэшировать старый IP; предпочтительны L7-веса/VRRP, а не DNS-switch.

### Рекомендованные ссылки

- **[Сравнение стратегий развертывания](./comparison.md)** — выбор между Rolling Update, Blue-Green и Canary.
- **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)** — автоматизация восстановления.
- **[Стратегии деплоя и rolling updates в Ansible](../../Ansible/ansible_deployment_strategies.md)** — полный reference по Rolling на Bare Metal.
