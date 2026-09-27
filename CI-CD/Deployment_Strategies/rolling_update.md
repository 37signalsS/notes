# Rolling Update — поэтапное обновление

> Обзорная стратегия развертывания, при которой экземпляры приложения заменяются поочередно или небольшими группами (батчами), обеспечивая непрерывную доступность сервиса. Детальные реализации по трекам **Kubernetes** и **традиционной инфраструктуры (Bare Metal / VM)** собраны в одном файле, чтобы избежать дублирования информации. Ссылки на смежные материалы: общее сравнение стратегий — в **[Сравнение стратегий развертывания](./comparison.md)**; интеграцию с проверками здоровья и откатом — в **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)**.

## Определения

**Rolling Update (Поэтапное обновление)** — стратегия развертывания (**Deployment**), при которой экземпляры приложения (**Pods**, виртуальные машины, контейнеры) обновляются поочередно или небольшими группами. Новая версия постепенно заменяет старую, обеспечивая непрерывную доступность сервиса.

- **Нулевое время простоя (Zero Downtime)** — ключевая цель стратегии, достигаемая за счет того, что часть экземпляров всегда остается в рабочем состоянии и готова принимать трафик через балансировщик.
- **Радиус поражения (Blast Radius)** — при Rolling Update радиус поражения ограничен количеством одновременно обновляемых подов (контролируется `maxUnavailable`).
- **Ревизия (Revision)** — сохраненное состояние манифеста, позволяющее выполнить откат.
- **Пакетная раскатка (Batch / Wave / Serial)** — обновление группы хостов (батча) с проверкой здоровья и паузой между волнами. Аналог `serial` в Ansible или `maxUnavailable`/`maxSurge` в Kubernetes, но применительно к физическим/виртуальным серверам.
- **Вывод из пула (Drain)** — процесс отключения узла от балансировщика (перевод в режим `drain`/`maintenance`) перед обновлением, чтобы он перестал принимать новые соединения (Connection Draining), при этом текущие запросы доживаются.
- **Бережное завершение (Graceful Shutdown)** — корректное завершение процесса: перехват `SIGTERM`, отказ от новых запросов, ожидание завершения активных (обычно 10–60 с) и только затем выход. Критично для отсутствия 502/504 при Rolling Update.
- **Проверка готовности (Health Check / Readiness)** — активная (балансировщик опрашивает `/healthz`) или пассивная (анализ 5xx/таймаутов) проверка того, что экземпляр готов принимать трафик. В традиционной среде реализуется через `option httpchk` в HAProxy или `health_check` в Nginx Plus; в Kubernetes — `readinessProbe`.
- **Партиционирование (Partition)** — параметр StatefulSet, ограничивающий обновление подами с индексом >= N, что позволяет реализовать Canary-обновление внутри Rolling Update.
- **Волновой подход (Wave / Progressive)** — деление батчей на несколько этапов с паузой и проверкой Golden Signals между ними (например, 10% → 25% → 50% → 100%).

## Основные концепции

### Механизм работы в Kubernetes

На уровне Kubernetes Rolling Update управляется контроллером Deployment, который манипулирует объектами **ReplicaSet**:
1.  **Создание нового RS:** При изменении шаблона пода (`spec.template`) создается новый ReplicaSet (v2).
2.  **Поэтапное масштабирование:** Контроллер увеличивает количество реплик в RS v2 и одновременно уменьшает в RS v1, соблюдая ограничения `maxSurge` и `maxUnavailable`.
3.  **Проверка готовности:** Удаление пода из старого RS происходит только после того, как новый под из RS v2 успешно прошел **Readiness Probe**.

Взаимодействие с другими контроллерами:
- **HPA (Horizontal Pod Autoscaler)** может конфликтовать с Rolling Update при `maxUnavailable: 0`, так как autoscaler перезаписывает `spec.replicas`. Решение: HPA должен управлять Deployment напрямую, а не ReplicaSet.
- **PDB (Pod Disruption Budget)** не ограничивает Rolling Update напрямую, но защищает от добровольных выселений (eviction) при плановых работах на узлах.

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

Ansible реализует батч-раскатку через `serial` и `max_fail_percentage`. Ниже — сокращенный паттерн; полный вариант с `block`/`rescue` автооткатом — в профильном материале: **[Стратегии деплоя и rolling updates в Ansible](../../Ansible/ansible_deployment_strategies.md)**.

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

Детали флагов, `--link-dest` для истории и ограничений безопасности — в профильном материале: **[rsync — синхронизация файлов](../../Linux/SystemAdministration/rsync.md)**.

## Операции и команды

### Kubernetes — управление стратегией Rolling Update

```bash
# Текущие параметры стратегии
kubectl get deployment myapp -o jsonpath='{.spec.strategy.type}{.spec.strategy.rollingUpdate}'
# → RollingUpdate{"maxSurge":"25%","maxUnavailable":"25%"}

# Пауза раскатки (paused) — для ручной валидации или совмещения с внешним Judge
kubectl rollout pause deployment/myapp

# Возобновление после паузы
kubectl rollout resume deployment/myapp

# Статус rollout
kubectl rollout status deployment/myapp --timeout=10m

# Откат на предыдущую ревизию
kubectl rollout undo deployment/myapp

# Откат с указанием конкретной ревизии
kubectl rollout undo deployment/myapp --to-revision=3

# Просмотр истории ревизий
kubectl rollout history deployment/myapp
```

### HAProxy — оперативное управление пулом при Rolling Update

```bash
# Статус бэкендов и ошибки через UNIX-сокет
echo "show stat" | socat - UNIX-CONNECT:/var/run/haproxy.sock | cut -d, -f1,2,18,35,36
# → колонки: pxname,svname,status,req.tot,eresp (eresp≠0 — растут ошибки)

# Вывод узла в drain
echo "set server app_servers/app1 state drain" | socat - UNIX-CONNECT:/var/run/haproxy.sock

# Возврат узла в ready
echo "set server app_servers/app1 state ready" | socat - UNIX-CONNECT:/var/run/haproxy.sock

# Принудительное завершение соединений на узле (для аварийного drain)
echo "show servers state" | socat - UNIX-CONNECT:/var/run/haproxy.sock
```

### Nginx — перезагрузка без downtime

```bash
# Проверка конфигурации перед применением
nginx -t

# Graceful reload (старые воркеры дожидают запросов)
nginx -s reload

# Статус upstream (если настроен stub_status)
curl -s http://localhost:9113/metrics | grep -E "nginx_upstream|http_requests_total"
```

### Ansible — паттерн Rolling Update с автооткатом

```yaml
---
- name: Rolling Update с ограничением батча и автооткатом
  hosts: webservers
  serial: "25%"             # 25% хостов за волну
  max_fail_percentage: 10   # остановить при 10% ошибок в батче
  any_errors_fail: true     # падение плейбука при ошибке
  tasks:
    - name: Drain host from LB
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/disable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost

    - name: Deploy new version
      ansible.builtin.apt:
        name: myapp
        state: latest

    - name: Restart service
      ansible.builtin.service:
        name: myapp
        state: restarted

    - name: Verify health
      ansible.builtin.uri:
        url: "http://{{ ansible_host }}/healthz"
        status_code: 200
      register: h
      retries: 15
      delay: 3
      until: h.status == 200

    - name: Return host to pool
      ansible.builtin.uri:
        url: "http://{{ lb_host }}/api/enable/{{ inventory_hostname }}"
        method: POST
      delegate_to: localhost
      when: h.status == 200
```

### systemd — атомарная смена версии и live property

```bash
# Атомарный откат/продвижение версии
ln -sfn /opt/app/2.4.0 /opt/app/current
systemctl restart myapp

# Проверка активности и health
systemctl is-active myapp
curl -sf http://localhost:8080/healthz
readlink /opt/app/current

# Изменение лимитов ресурсов без рестарта (In-Place Resize аналог)
systemctl set-property myapp.service MemoryMax=2G CPUQuota=150%
systemctl show myapp.service -p MemoryMax,CPUQuota
```

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
| **Deadlock при Rolling Update** | Новые поды не могут встать на узлы из-за podAntiAffinity без `matchLabelKeys`. | Использовать `matchLabelKeys` (v1.31+) для разделения версий при Anti-Affinity. |
| **HPA конфликтует с Rolling Update** | Autoscaler перезаписывает `replicas` во время rollout. | HPA должен управлять Deployment, а не ReplicaSet; мониторить совместное поведение. |
| **Rolling Update обрывает WebSocket/long-polling** | Drain закрывает активные соединения. | Поддержка `Connection: keep-alive` и `Upgrade` в балансировщике; отказ от sticky на период drain. |
| **Старая версия остается после отката** | Rollback оставляет артефакт на диске или не сбрасывает symlink. | Добавить post-rollback cleanup hook в CI (удаление версий старше N последних). |
| **Узел остался в UP после Rolling** | Health-check возвращает `200`, но приложение фактически устарело. | Проверить, что `httpchk` проверяет реальный эндпоинт приложения, а не только порт. |
| **StatefulSet partition застрял** | Обновленный под с индексом < partition не становится Ready. | Вернуть шаблон (`rollout undo`) и удалить поды с плохой ревизией вручную. |
| **Симлинк на NFS (atomic rename не работает)** | NFS не гарантирует атомарность `ln -sfn` при переключении symlink. | Использовать `rename(2)` через `mv -T` на локальных ФС; на NFS — деплой через rsync на новый каталог + переключение через `ln -s` с проверкой `stat`. |
| **Graceful shutdown не успевает завершить запросы** | `TimeoutStopSec` в systemd меньше максимальной длительности запроса. | Увеличить `TimeoutStopSec` до покрытия P99 длительности + запас; в приложении увеличить лимит активных соединений перед `SIGTERM`. |

## Лучшие практики

1.  **Иммутабельность:** Никогда не используйте тег `:latest`. Обновление должно инициироваться сменой конкретной версии образа или хеша конфигурации.
2.  **Expand and Contract:** При обновлении работают две версии приложения. База данных должна поддерживать обе схемы одновременно. Подробнее: **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**.
3.  **PDB (Pod Disruption Budget):** Не ограничивает Rolling Update напрямую, но важен для стабильности при одновременных работах на узлах. Подробнее: **[Pod Disruption Budget](../../Kubernetes/Autoscaling/pod_disruption_budget.md)**.
4.  **Волновая раскатка (Wave / Progressive):** Делите узлы на волны (10% → 25% → 50% → 100%) с паузой и проверкой Golden Signals между ними. Это превращает Rolling в Progressive Delivery даже без Kubernetes.
5.  **Атомарность артефакта:** Используйте versioned-каталоги + symlink (`/opt/app/current`) или immutable-образы, чтобы откат был мгновенным (`ln -sfn` на предыдущую версию).
6.  **Idempotent operations:** Каждый шаг раскатки (Ansible task, bash-скрипт) должен быть идемпотентным: повторный запуск не ломает систему и приводит в то же состояние.
7.  **Checksum-верификация артефактов:** Проверяйте хеш бинарника/образа после доставки (SHA256) и только затем переключайте symlink или обновляйте Deployment.
8.  **Observation window:** После каждого батча фиксируйте Error Rate, P95 Latency и Saturation за фиксированное окно времени (например, 60–120 с) перед продолжением.
9.  **Fail-closed при отсутствии данных:** Если Judge/мониторинг недоступен или метрики не собраны — раскатка останавливается, а не продолжается вслепую.
10. **Graceful shutdown обязателен:** Приложение должно перехватывать `SIGTERM`, отказываться от новых запросов и дожидаться активных соединений. Без этого drain приведет к 502/504.
11. **Версионирование миграций БД:** Каждая миграция должна иметь уникальный номер/хеш и быть обратно-совместимой. Откат кода без отката миграции допустим только при Expand-Contract.
12. **Управление sticky-сессиями:** При Rolling Update внешний session store (Redis, Memcached) снижает риск обрыва пользовательских сессий при drain. Если sticky неизбежен — отключайте его на период обновления пула.

## Интеграция с GitLab CI/CD

### Полный пайплайн Rolling Update с approval gate

```yaml
stages:
  - build
  - test
  - deploy
  - verify

variables:
  IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  KUBE_CONTEXT: ops/k8s-infra:production-agent

build_image:
  stage: build
  image: docker:29.8
  services:
    - docker:29.8-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $IMAGE_TAG .
    - docker push $IMAGE_TAG
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_rolling:
  stage: deploy
  image: bitnami/kubectl:1.37
  needs:
    - build_image
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl set image deployment/my-app app=$IMAGE_TAG
    - kubectl rollout status deployment/my-app --timeout=10m
  environment:
    name: production
    url: https://app.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

verify_rolling:
  stage: verify
  image: curlimages/curl:8.22.0
  needs:
    - deploy_rolling
  script:
    - |
      for i in 1 2 3; do
        code=$(curl -s -o /dev/null -w "%{http_code}" https://app.example.com/healthz)
        [ "$code" = "200" ] && break || sleep 10
      done
      [ "$(curl -s -o /dev/null -w "%{http_code}" https://app.example.com/healthz)" = "200" ]
  environment:
    name: production
```

### Автоматический откат через GitLab CI + Prometheus

```yaml
stages:
  - deploy
  - monitor
  - rollback

deploy_canary:
  stage: deploy
  image: bitnami/kubectl:1.37
  script:
    - kubectl set image deployment/my-app app=$IMAGE_TAG
    - kubectl rollout status deployment/my-app --timeout=10m
  environment:
    name: production

monitor_metrics:
  stage: monitor
  image: curlimages/curl:8.22.0
  needs:
    - deploy_canary
  script:
    - |
      ERROR_RATE=$(curl -s "http://prometheus:9090/api/v1/query?query=sum(rate(http_requests_total{status=~'5..'}[5m]))/sum(rate(http_requests_total[5m]))" | jq '.data.result[0].value[1]')
      if (( $(echo "$ERROR_RATE > 0.01" | bc -l) )); then
        echo "CRITICAL: Error rate $ERROR_RATE > 1%. Initiating Rollback..."
        exit 1
      fi

auto_rollback:
  stage: rollback
  image: bitnami/kubectl:1.37
  needs:
    - monitor_metrics
  script:
    - kubectl rollout undo deployment/my-app
    - kubectl rollout status deployment/my-app --timeout=5m
  environment:
    name: production
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### Rolling Update для традиционной инфраструктуры (Ansible + GitLab CI)

```yaml
stages:
  - validate
  - deploy
  - verify

ansible_lint:
  stage: validate
  image: cytopia/ansible-lint:latest
  script:
    - ansible-lint playbooks/deploy.yml

rolling_update:
  stage: deploy
  image: cytopia/ansible:2.14
  needs:
    - ansible_lint
  script:
    - ansible-playbook -i inventory/production playbooks/rolling_update.yml \
        --extra-vars "app_version=${CI_COMMIT_TAG}"
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

health_check:
  stage: verify
  image: curlimages/curl:8.22.0
  needs:
    - rolling_update
  script:
    - ansible -i inventory/production all -m uri -a "url=http://{{ inventory_hostname }}:8080/healthz status_code=200"
```

## Дополнительная информация

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
- **Время прогревов (Warm-up):** Приложения с JIT-компиляцией (Java, Go) или прогревом кэшей (ML-модели) требуют `minReadySeconds` ≥ 30–60 с, иначе первый батч Rolling Update получит деградированные latency/p95.
- **Аппаратная неоднородность:** Узлы одного пула могут различаться по CPU/объёму памяти; при Rolling важно проверять `lscpu`/`free -h` и не смешивать несовместимые ядра.
- **Резервирование ёмкости:** под Rolling нужен минимум N+1, под Blue-Green — 2x ресурсов (учитывайте лимиты лицензий ПО).

### Рекомендованные ссылки

- **[Сравнение стратегий развертывания](./comparison.md)** — выбор между Rolling Update, Blue-Green и Canary.
- **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)** — автоматизация восстановления.
- **[Стратегии деплоя и rolling updates в Ansible](../../Ansible/ansible_deployment_strategies.md)** — полный reference по Rolling на Bare Metal.
