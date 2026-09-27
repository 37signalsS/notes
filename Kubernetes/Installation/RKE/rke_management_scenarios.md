# RKE: Управление и поиск неисправностей

> [!WARNING]
> **RKE1 достиг конца жизненного цикла (EOL) 31 июля 2025 года.** 
> Поддержка прекращена, основное внимание Rancher Labs полностью переключено на **RKE2**. Используйте данный раздел исключительно для поддержки существующих Legacy-кластеров.

## Определения

**RKE CLI** — утилита командной строки, предназначенная для развертывания, обновления и обслуживания кластеров RKE1. Работает по принципу "запуск из любого места", так как не требует локальной установки Kubernetes на узлах. Взаимодействует с узлами через SSH и Docker API.

**cluster.rkestate** — критически важный файл состояния кластера в формате JSON. Содержит полную копию конфигурации `cluster.yml`, все сгенерированные TLS-сертификаты и ключи, текущее состояние ресурсов и метаданные кластера. При потере этого файла управление кластером через RKE CLI (обновление, ротация сертификатов, масштабирование) становится невозможным. Файл автоматически обновляется при каждом запуске `rke up`.

**cluster.yml** — декларативный файл конфигурации кластера. Описывает желаемое состояние: узлы с их ролями, сетевые плагины, версию Kubernetes, опции Docker, параметры сервисов и аддоны. RKE сверяет текущее состояние кластера (из `cluster.rkestate`) с `cluster.yml` и применяет необходимые изменения.

**kube_config_cluster.yml** — файл конфигурации kubectl, содержащий адрес API-сервера и сертификаты аутентификации администратора. Генерируется автоматически при первом успешном `rke up`. Этот файл необходим для управления кластером через kubectl.

**Ротация сертификатов (Certificate Rotation)** — процедура обновления TLS-сертификатов всех системных компонентов Kubernetes (kube-apiserver, kubelet, kube-proxy, etcd, kube-scheduler, kube-controller-manager). RKE управляет этим процессом централизованно через SSH, автоматически заменяя сертификаты и перезапуская затронутые компоненты.

**Снимок (Snapshot) etcd** — полная резервная копия базы данных etcd, включая все секреты, конфигурации и состояние объектов Kubernetes. Сохраняется на всех узлах с ролью `etcd` в директории `/opt/rke/etcd-snapshots/`. Снимки можно создавать вручную или автоматизировать через cron.

**rke-tools** — вспомогательный образ контейнера (Docker image), используемый RKE для выполнения системных операций на узлах: подготовка конфигураций, ротация сертификатов, создание снимков etcd, управление контейнерами. Автоматически скачивается при каждом запуске `rke up`.

**Дренаж узла (Node Drain)** — процесс безопасного вывода узла из эксплуатации: перемещение подов на другие узлы, исключение узла из распределения нагрузки, корректная остановка сервисов. В RKE выполняется через `kubectl drain`, так как RKE CLI не предоставляет встроенной команды дренажа.

## Базовые концепции

### Инструментарий управления

*   **RKE CLI**: Основной инструмент для "Day 0" (установка) и "Day 2" (обслуживание вне Rancher). Все команды выполняются относительно файла конфигурации `cluster.yml`. RKE CLI не требует установленного kubectl или Kubernetes на локальной машине — он управляет кластером напрямую через SSH и Docker.
*   **Rancher UI**: Если кластер импортирован в Rancher, большинство операций (бэкапы, ротация, обновление) доступны через веб-интерфейс, который под капотом вызывает RKE CLI. Rancher добавляет дополнительные возможности: визуальный мониторинг, управление проектами, RBAC.
*   **SSH-доступ**: RKE требует беспарольный доступ по SSH к каждому узлу от имени пользователя с правами запуска Docker (обычно член группы `docker`). Проверка доступа: `ssh user@node-ip "docker ps"`.
*   **kubectl**: Стандартный клиент для взаимодействия с API-сервером. Используется для проверки состояния кластера после выполнения операций RKE.

### Жизненный цикл кластера

```
Day 0: Развертывание
  └── cluster.yml → rke up → kube_config_cluster.yml + cluster.rkestate

Day 1: Эксплуатация
  └── cluster.yml (правки) → rke up → обновление кластера
  └── rke etcd snapshot-save → резервное копирование
  └── rke cert rotate → ротация сертификатов

Day 2: Обслуживание
  └── Масштабирование (rke up с измененным cluster.yml)
  └── Обновление версий Kubernetes (kubernetes_version в cluster.yml)
  └── Disaster Recovery (rke etcd snapshot-restore)
  └── Вывод узлов (kubectl drain + rke up без узла)

End of Life: Завершение эксплуатации
  └── rke remove → полное удаление кластера
  └── Миграция на RKE2
```

### Порядок действий (Workflow)

Любое действие в RKE следует циклу:
1.  Правка `cluster.yml` (если применимо).
2.  Запуск `rke up --config cluster.yml`.
3.  Проверка `cluster.rkestate` (обновляется автоматически).
4.  Проверка доступности API через kubectl: `kubectl cluster-info`.
5.  Проверка состояния узлов: `kubectl get nodes -o wide`.
6.  Проверка системных подов: `kubectl get pods -n kube-system`.

### Предварительные требования к узлам

Перед запуском любых операций RKE убедитесь в выполнении требований:

```bash
# 1. Docker установлен и запущен на каждом узле
ssh user@node "docker --version"
# → Docker version 24.0.x или 20.10.x (проверьте совместимость с версией RKE)

# 2. SSH-доступ без пароля работает
ssh user@node "echo SSH_OK"
# → SSH_OK

# 3. Пользователь имеет права docker-группы
ssh user@node "id -nG"
# → docker sudo (или аналогичная группа)

# 4. Хронометраж синхронизирован (NTP)
ssh user@node "timedatectl status | grep 'NTP service'"
# → NTP service: active

# 5. Порты доступны (базовая проверка)
ssh user@node "nc -zv localhost 2379 2380 6443 10250 10251 10252 10257 10259"
# → Connection to localhost 2379 port [tcp/etcd-server] succeeded!
# → Connection to localhost 2380 port [tcp/etcd-server-ssl] succeeded!
# → ... (все порты должны быть доступны)

# 6. Достаточно дискового пространства
ssh user@node "df -h / /var/lib/docker /opt/rke"
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1        50G   12G   36G  25% /
# → /dev/sdb1       200G   45G  145G  24% /var/lib/docker
```

## Практические сценарии

### Установка RKE CLI

Для управления кластером необходимо использовать последнюю стабильную версию утилиты.

```bash
# Скачивание версии v1.8.14 (последняя стабильная версия для RKE1)
# Для Linux (amd64):
curl -L https://github.com/rancher/rke/releases/download/v1.8.14/rke_linux-amd64 -o rke

# Для macOS (Intel):
curl -L https://github.com/rancher/rke/releases/download/v1.8.14/rke_darwin-amd64 -o rke

# Для macOS (Apple Silicon):
curl -L https://github.com/rancher/rke/releases/download/v1.8.14/rke_darwin-arm64 -o rke

# Установка прав и перемещение в системный PATH
chmod +x rke
sudo mv rke /usr/local/bin/

# Проверка корректности установки
rke --version
# → rke version v1.8.14
```

### Генерация и валидация cluster.yml

RKE может сгенерировать минимальный шаблон конфигурации или вы можете создать его вручную.

```bash
# Генерация шаблона cluster.yml с интерактивным вводом
rke config

# Просмотр текущего cluster.yml
cat cluster.yml

# Валидация cluster.yml (проверка синтаксиса)
# RKE автоматически проверяет конфигурацию при запуске rke up
# Если есть ошибки, он выдаст сообщение с указанием проблемы

# Проверка доступности узлов перед запуском
rke up --config cluster.yml --dry-run
# → Не существует флага --dry-run в RKE, но можно проверить вручную:
# 1. Проверить SSH-доступ ко всем узлам
# 2. Проверить Docker на каждом узле
# 3. Проверить сетевую связность между узлами
```

### Просмотр состояния кластера

```bash
# Проверка доступности API-сервера
kubectl cluster-info
# → Kubernetes control plane is running at https://192.168.1.100:6443
# → CoreDNS is running at https://192.168.1.100:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy

# Просмотр узлов с ролями и версиями
kubectl get nodes -o wide
# → NAME       STATUS   ROLES                      AGE   VERSION   INTERNAL-IP     OS-IMAGE
# → node-01    Ready    controlplane,etcd,worker   30d   v1.28.10  192.168.1.10   Ubuntu 22.04.3 LTS
# → node-02    Ready    controlplane,etcd,worker   30d   v1.28.10  192.168.1.11   Ubuntu 22.04.3 LTS
# → node-03    Ready    controlplane,etcd,worker   30d   v1.28.10  192.168.1.12   Ubuntu 22.04.3 LTS

# Просмотр системных подов
kubectl get pods -n kube-system -o wide
# → NAME                                       READY   STATUS    RESTARTS   AGE   IP            NODE
# → coredns-7ff77c879f-xxxxx                   1/1     Running   0          30d   10.42.0.2     node-01
# → ingress-nginx-controller-xxxxx              1/1     Running   0          30d   192.168.1.10  node-01
# → kube-apiserver-node-01                      1/1     Running   0          30d   192.168.1.10  node-01
# → kube-controller-manager-node-01             1/1     Running   0          30d   192.168.1.10  node-01
# → kube-proxy-xxxxx                            1/1     Running   0          30d   192.168.1.10  node-01
# → kube-scheduler-node-01                      1/1     Running   0          30d   192.168.1.10  node-01
# → metrics-server-xxxxx                        1/1     Running   0          30d   10.42.0.3     node-01
# → canal-xxxxx                                 2/2     Running   0          30d   192.168.1.10  node-01

# Проверка версии сервера
kubectl version --short
# → Client Version: v1.28.10
# → Server Version: v1.28.10

# Просмотр событий кластера (последние ошибки)
kubectl get events -n kube-system --sort-by='.lastTimestamp' | tail -20

# Проверка здоровья etcd кластера (через API-сервер)
kubectl get --raw /healthz/etcd
# → ok

# Проверка компонентов control plane
kubectl get componentstatuses
# → NAME                 STATUS    MESSAGE             ERROR
# → controller-manager   Healthy   ok
# → scheduler            Healthy   ok
# → etcd-0               Healthy   {"health":"true"}
```

### Масштабирование: Добавление и удаление узлов

RKE не поддерживает автоматическое масштабирование (в отличие от Kubespray или Rancher). Все операции выполняются вручную через правку `cluster.yml` и запуск `rke up`.

**Добавление узла:**

```bash
# 1. Подготовьте новый узел:
#    - Установите Docker (версию, совместимую с RKE)
#    - Настройте SSH-доступ без пароля
#    - Убедитесь, что узел доступен по сети со всех узлов кластера

# 2. Проверьте SSH-доступ с машины, где установлен RKE
ssh user@new-node-ip "docker ps && echo SSH_OK"

# 3. Добавьте описание узла в секцию nodes файла cluster.yml
# Пример для worker-узла:
cat >> cluster.yml <<'EOF'
nodes:
  - address: 192.168.1.13
    user: ubuntu
    role: [worker]
    labels:
      environment: production
      disktype: ssd
EOF

# 4. Запустите обновление кластера
rke up --config cluster.yml

# 5. Проверьте, что узел добавился
kubectl get nodes -o wide
# → NAME       STATUS   ROLES                      AGE     VERSION   INTERNAL-IP
# → node-01    Ready    controlplane,etcd,worker   30d     v1.28.10  192.168.1.10
# → node-02    Ready    controlplane,etcd,worker   30d     v1.28.10  192.168.1.11
# → node-03    Ready    controlplane,etcd,worker   30d     v1.28.10  192.168.1.12
# → node-04    Ready    worker                     5m      v1.28.10  192.168.1.13
```

**Удаление узла:**

```bash
# 1. Если узел worker: безопасно выведите поды
kubectl drain node-04 --ignore-daemonsets --delete-emptydir-data --force

# 2. Удалите описание узла из cluster.yml
# (отредактируйте файл и удалите соответствующий блок из секции nodes)

# 3. Запустите обновление кластера
rke up --config cluster.yml
# → RKE остановит контейнеры на удаленном узле и перенастроит кластер.

# 4. Проверьте, что узел удален
kubectl get nodes -o wide
# → NAME       STATUS   ROLES                      AGE     VERSION   INTERNAL-IP
# → node-01    Ready    controlplane,etcd,worker   30d     v1.28.10  192.168.1.10
# → node-02    Ready    controlplane,etcd,worker   30d     v1.28.10  192.168.1.11
# → node-03    Ready    controlplane,etcd,worker   30d     v1.28.10  192.168.1.12

# 5. Очистите остатки на удаленном узле (опционально)
ssh user@removed-node "docker system prune -af && sudo rm -rf /opt/rke /etc/kubernetes"
```

**Замена узла (role change):**

```bash
# Если нужно изменить роль узла (например, добавить etcd на worker)
# 1. Обновите роль в cluster.yml
# 2. Запустите rke up
# RKE перенастроит компоненты на этом узле

# Пример: добавление роли etcd на существующий worker-узел
# В cluster.yml измените:
#   - address: 192.168.1.13
#     role: [worker]  →  role: [worker, etcd]
```

### Обновление версии Kubernetes

Поскольку RKE1 находится в режиме EOL, новые версии выпускаются редко и только для закрытия критических уязвимостей. Обновление происходит через изменение `kubernetes_version` в `cluster.yml`.

```yaml
# В файле cluster.yml
kubernetes_version: "v1.28.10-rancher1-1"
```

```bash
# Проверка доступных версий
rke config --list-version --all
# → v1.28.10-rancher1-1
# → v1.27.14-rancher1-1
# → v1.26.15-rancher1-1

# Обновление кластера
rke up --config cluster.yml

# При запуске rke up процесс обновления происходит последовательно:
# 1. Обновление компонентов на etcd-узлах (один за другим)
# 2. Обновление controlplane-узлов (rolling update)
# 3. Поочередное обновление worker-узлов (rolling update с контролем_pod_disruption_budget)

# Проверка после обновления
kubectl get nodes -o wide
# → NAME       STATUS   ROLES                      AGE   VERSION   INTERNAL-IP
# → node-01    Ready    controlplane,etcd,worker   30d   v1.28.10  192.168.1.10

kubectl version --short
# → Server Version: v1.28.10-rancher1-1
```

> [!IMPORTANT]
> При обновлении версии Kubernetes в RKE1 обновляются ВСЕ компоненты (control plane + worker). Невозможно обновить только worker-узлы или только control plane. Процесс идемпотентен — повторный запуск `rke up` с той же версией не вызовет повторного обновления.

### Резервное копирование и восстановление etcd

**Создание снимка:**

Снимки сохраняются на всех узлах с ролью `etcd` в директории `/opt/rke/etcd-snapshots/`. Рекомендуется создавать снимки перед каждым изменением конфигурации и регулярно (через cron).

```bash
# Создание снимка с именем, содержащим дату
rke etcd snapshot-save --name backup-$(date +%F) --config cluster.yml
# → INFO[0000] Sending image [rancher/rke-tools:v0.1.99] to nodes
# → INFO[0015] Finished saving snapshot [backup-2026-08-07] on all etcd nodes

# Создание снимка с описанием
rke etcd snapshot-save --name pre-upgrade-v1.28.10 --config cluster.yml

# Просмотр созданных снимков на узле
ssh user@etcd-node "ls -la /opt/rke/etcd-snapshots/"
# → total 1.2G
# → -rw------- 1 root root  512M Aug  7 12:00 backup-2026-08-07
# → -rw------- 1 root root  512M Aug  7 12:05 pre-upgrade-v1.28.10

# Просмотр размера снимка
ssh user@etcd-node "du -sh /opt/rke/etcd-snapshots/"
# → 1.2G    /opt/rke/etcd-snapshots/
```

**Автоматизация резервного копирования (cron):**

```bash
# Добавление задачи в cron на машине с RKE CLI
# Каждый день в 2:00
crontab -e

# Добавьте строку:
0 2 * * * /usr/local/bin/rke etcd snapshot-save --name backup-$(date +\%F) --config /path/to/cluster.yml >> /var/log/rke-backup.log 2>&1

# Проверка задач cron
crontab -l
# → 0 2 * * * /usr/local/bin/rke etcd snapshot-save --name backup-$(date +\%F) --config /path/to/cluster.yml >> /var/log/rke-backup.log 2>&1
```

**Ротация снимков (удаление старых):**

```bash
# Удаление снимков старше 7 дней на всех etcd-узлах
ssh user@etcd-node "find /opt/rke/etcd-snapshots/ -name '*.db' -mtime +7 -delete"

# Или удаление снимков, оставляя только последние 3
ssh user@etcd-node "ls -t /opt/rke/etcd-snapshots/*.db | tail -n +4 | xargs rm -f"
```

**Восстановление из снимка:**

Процесс требует перезапуска всех компонентов кластера. Кластер будет недоступен на время восстановления.

```bash
# Восстановление из конкретного снимка
rke etcd snapshot-restore --name backup-2026-08-07 --config cluster.yml
# → INFO[0000] Restoring snapshot [backup-2026-08-07]
# → INFO[0045] Finished restoring snapshot successfully

# После восстановления проверьте кластер
kubectl get nodes -o wide
kubectl get pods -n kube-system

# Проверка etcd
kubectl get --raw /healthz/etcd
# → ok
```

> [!WARNING]
> После восстановления из снимка ВСЕ изменения, произошедшие после создания снимка, будут потеряны. Убедитесь, что вы используете актуальный снимок.

**Просмотр информации о снимке:**

```bash
# Через Docker (на etcd-узле)
ssh user@etcd-node "docker run --rm -v /opt/rke/etcd-snapshots:/snapshots rancher/rke-tools:v0.1.99 etcdutl snapshot status /snapshots/backup-2026-08-07 --write-out=table"
# → +---------+----------+------------+------------+
# → |  HASH   | REVISION | TOTAL KEYS | TOTAL SIZE |
# → +---------+----------+------------+------------+
# → | xxxxxxx |   123456 |     125430 |     512 MB |
# → +---------+----------+------------+------------+
```

### Управление сертификатами

**Просмотр информации о сертификатах:**

```bash
# Проверка сроков действия сертификатов на узле
ssh user@master-node "ls -la /etc/kubernetes/ssl/"
# → total 48
# → -rw------- 1 root root  1675 Aug  7 12:00 kube-apiserver.key
# → -rw------- 1 root root  3969 Aug  7 12:00 kube-apiserver.crt
# → -rw------- 1 root root  1675 Aug  7 12:00 kube-apiserver-proxy-client.key
# → -rw------- 1 root root  1107 Aug  7 12:00 kube-apiserver-proxy-client.crt
# → -rw------- 1 root root  1675 Aug  7 12:00 kube-controller-manager.key
# → -rw------- 1 root root  3829 Aug  7 12:00 kube-controller-manager.crt
# → -rw------- 1 root root  1675 Aug  7 12:00 kube-scheduler.key
# → -rw------- 1 root root  3829 Aug  7 12:00 kube-scheduler.crt
# → ...

# Просмотр даты истечения сертификата API-сервера
ssh user@master-node "openssl x509 -in /etc/kubernetes/ssl/kube-apiserver.crt -noout -dates"
# → notBefore=Aug  7 12:00:00 2026 GMT
# → notAfter=Aug  7 12:00:00 2027 GMT

# Просмотр информации о сертификате (владелец, издатель)
ssh user@master-node "openssl x509 -in /etc/kubernetes/ssl/kube-apiserver.crt -noout -subject -issuer"
# → subject= /CN=kube-apiserver
# → issuer= /CN=kube-apiserver-ca
```

**Ротация всех сертификатов:**

```bash
# Ротация всех сертификатов (kube-apiserver, kubelet, etcd, и т.д.)
rke cert rotate --config cluster.yml
# → INFO[0000] Rotating SSL certificates
# → INFO[0030] Successfully rotated certificates

# После ротации проверьте работоспособность кластера
kubectl get nodes -o wide
kubectl get pods -n kube-system

# Обновите kubeconfig на локальной машине (сертификаты изменились)
# Скопируйте новый kube_config_cluster.yml
cat kube_config_cluster.yml > ~/.kube/config
```

**Ротация сертификатов конкретного сервиса:**

```bash
# Ротация только для kubelet
rke cert rotate --service kubelet --config cluster.yml
# → INFO[0000] Rotating kubelet certificates
# → INFO[0015] Successfully rotated kubelet certificates

# Ротация только для kube-apiserver
rke cert rotate --service kube-apiserver --config cluster.yml

# Ротация только для etcd
rke cert rotate --service etcd --config cluster.yml

# Ротация только для kube-proxy
rke cert rotate --service kube-proxy --config cluster.yml
```

**Ротация CA (Certificate Authority):**

```bash
# Ротация корневого сертификата CA — наиболее опасная операция
# Все сертификаты будут перевыпущены заново
rke cert rotate --rotate-ca --config cluster.yml
# → INFO[0000] Rotating CA certificates
# → INFO[0120] Successfully rotated CA certificates

# После ротации CA ОБЯЗАТЕЛЬНО:
# 1. Обновить kube_config_cluster.yml на всех машинах администраторов
# 2. Обновить kubeconfig для CI/CD систем
# 3. Проверить, что все сервисы используют новые сертификаты
# 4. Обновить файл cluster.rkestate (он обновляется автоматически)
```

> [!WARNING]
> Ротация CA — наиболее рискованная операция. Все клиентские сертификаты будут перевыпущены. Убедитесь, что у вас есть доступ к мастер-узлам по SSH на случай проблем.

### Вывод узла из эксплуатации (Maintenance)

```bash
# 1. Пометьте узел как нераспределяемый (чтобы не запускались новые поды)
kubectl cordon node-02

# 2. Безопасно выведите существующие поды (кроме DaemonSet)
kubectl drain node-02 \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --force \
  --grace-period=60
# → node/node-02 cordoned
# → WARNING: ignoring DaemonSet-managed pods
# → Evicting pod "nginx-xxx" from node-02
# → pod/nginx-xxx evicted

# 3. Выполните необходимые работы на узле (обновление ОС, Docker, и т.д.)
ssh user@node-02 "sudo apt update && sudo apt upgrade -y"
ssh user@node-02 "sudo reboot"

# 4. Дождитесь перезагрузки узла
ssh user@node-02 "uptime"

# 5. Пометьте узел как распределяемый
kubectl uncordon node-02

# 6. Проверьте, что узел вернулся в кластер
kubectl get nodes -o wide
# → NAME       STATUS   ROLES                      AGE   VERSION   INTERNAL-IP
# → node-02    Ready    controlplane,etcd,worker   30d   v1.28.10  192.168.1.11
```

### Полное удаление кластера

```bash
# Удаление кластера (остановит и удалит все контейнеры на узлах)
# ВНИМАНИЕ: Это необратимая операция!
rke remove --config cluster.yml
# → INFO[0000] Removing Docker containers from nodes
# → INFO[0030] Successfully removed cluster

# После удаления:
# 1. Все контейнеры Kubernetes будут удалены с узлов
# 2. Все данные в /opt/rke будут удалены
# 3. Файлы конфигурации (cluster.yml, cluster.rkestate, kube_config_cluster.yml) останутся на локальной машине

# Очистка локальных файлов (опционально)
rm -f cluster.yml cluster.rkestate kube_config_cluster.yml

# Очистка kubeconfig на локальной машине
kubectl config delete-context production-admin
rm -f ~/.kube/config
```

### Диагностика через Docker (когда kubectl недоступен)

Если API-сервер недоступен и kubectl не работает, проверяйте логи напрямую на узлах через Docker.

```bash
# Проверка состояния компонентов на мастер-узле
ssh user@master-node "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
# → NAMES                           STATUS          PORTS
# → kube-apiserver                  Up 30 days      0.0.0.0:6443->6443/tcp
# → kube-controller-manager         Up 30 days
# → kube-scheduler                  Up 30 days
# → etcd                            Up 30 days      0.0.0.0:2379-2380->2379-2380/tcp

# Просмотр логов etcd при ошибках кворума
ssh user@etcd-node "docker logs etcd 2>&1 | tail -50"
# → {"level":"warn","msg":"failed to reconcile...","time":"2026-08-07T12:00:00Z"}

# Просмотр ошибок в логах etcd
ssh user@etcd-node "docker logs etcd 2>&1 | grep -i 'error\|warn' | tail -20"

# Проверка логов kube-apiserver при проблемах с авторизацией
ssh user@master-node "docker logs kube-apiserver 2>&1 | grep -i 'unauthorized\|forbidden' | tail -10"

# Проверка логов kubelet на worker-узлах
ssh user@worker-node "docker logs kubelet 2>&1 | tail -30"

# Проверка логов kube-proxy
ssh user@worker-node "docker logs kube-proxy 2>&1 | tail -20"

# Проверка состояния сети (Flannel/Canal)
ssh user@worker-node "docker logs canal 2>&1 | grep -i 'error' | tail -10"

# Просмотр всех логов компонентов (красивый вывод)
ssh user@master-node "for c in kube-apiserver kube-controller-manager kube-scheduler; do echo '=== $c ==='; docker logs $c 2>&1 | tail -5; done"
```

### Диагностика сети

```bash
# Проверка сетевых интерфейсов
ssh user@node "ip addr show | grep -E 'inet |flannel|calico|vxlan'"
# → inet 192.168.1.10/24 brd 192.168.1.255 scope global eth0
# → inet 10.42.0.1/16 scope global flannel.1

# Проверка маршрутов
ssh user@node "ip route show"
# → default via 192.168.1.1 dev eth0 proto dhcp
# → 10.42.0.0/16 dev flannel.1 proto kernel scope link src 10.42.0.0
# → 10.42.1.0/24 via 10.42.1.0 dev flannel.1 proto static
# → 10.42.2.0/24 via 10.42.2.0 dev flannel.1 proto static

# Проверка DNS
kubectl run dnstest --image=busybox:1.36 --rm -it --restart=Never -- nslookup kubernetes.default
# → Server:    10.43.0.10
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.43.0.1

# Проверка доступности API-сервера из пода
kubectl run apitest --image=curlimages/curl --rm -it --restart=Never -- curl -sk https://kubernetes.default.svc.cluster.local/version
# → {"major":"1","minor":"28","gitVersion":"v1.28.10",...}

# Проверка доступности между узлами
ssh user@node-1 "ping -c 3 192.168.1.11"
# → PING 192.168.1.11 (192.168.1.11) 56(84) bytes of data.
# → 64 bytes from 192.168.1.11: icmp_seq=1 ttl=64 time=0.5 ms
```

## Поиск и устранение неисправностей

### Типичные ошибки и их решения

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **`x509: certificate has expired`** | Истек сертификат API-сервера или клиентский сертификат | `rke cert rotate --config cluster.yml`. Проверьте даты: `openssl x509 -in /etc/kubernetes/ssl/kube-apiserver.crt -noout -dates` |
| **`Unable to connect to the server: Connection refused`** | API-сервер недоступен или неверный IP/порт в kubeconfig | Проверьте порт 6443: `nc -zv <api-ip> 6443`. Убедитесь, что контейнер запущен: `docker ps \| grep kube-apiserver` |
| **`error: You must be logged in to the server (Unauthorized)`** | kubeconfig устарел или был перегенерирован | Скопируйте актуальный `kube_config_cluster.yml` с локальной машины или выполните `rke up` для обновления |
| **`error: the server doesn't have a resource type "nodes"`** | Несоответствие версий клиента и сервера | Проверьте версию: `kubectl version`. Обновите kubectl или получите новый kubeconfig |
| **`certificate signed by unknown authority`** | CA-сертификат в kubeconfig не соответствует серверному | Скопируйте актуальный `kube_config_cluster.yml` или получите новый CA с мастер-узла |
| **`connection timed out`** | Сетевые проблемы или файрвол блокирует порт 6443 | Проверьте маршрутизацию: `traceroute <api-ip>`. Проверьте файрвол: `iptables -L -n \| grep 6443` |
| **`rke up` завершается с ошибкой `failed to create SSH connection`** | Нет SSH-доступа к узлу | Проверьте SSH: `ssh user@node "echo OK"`. Убедитесь, что ключ добавлен в `authorized_keys` |
| **`rke up` зависает на этапе `Waiting for etcd to be available`** | etcd-кластер не может сформировать кворум | Проверьте логи etcd: `docker logs etcd`. Убедитесь, что все etcd-узлы доступны по сети |
| **`rke up` завершается с `Unable to access Docker Hub`** | Нет доступа к реестру образов | Проверьте DNS и интернет-доступ. Используйте зеркало реестра в `cluster.yml` |
| **Поды в `ImagePullBackOff`** | Нет доступа к реестру образов или неверный токен | Проверьте `imagePullSecrets` и доступ к registry. Для приватных реестров: `kubectl create secret docker-registry` |
| **`etcd cluster ID mismatch`** | Различия в ID кластера etcd | Восстановите из снимка: `rke etcd snapshot-restore --name <backup> --config cluster.yml` |
| **`rke up` сообщает `cluster.yml is missing`** | Файл конфигурации не найден | Убедитесь, что вы находитесь в правильной директории или укажите путь: `rke up --config /path/to/cluster.yml` |

### Восстановление при повреждении cluster.rkestate

Если файл `cluster.rkestate` поврежден или удален, но кластер работает:

```bash
# Вариант 1: Попробуйте запустить rke up — RKE попытается восстановить состояние
rke up --config cluster.yml
# RKE обнаружит расхождение и попытается восстановить состояние из работающих контейнеров

# Вариант 2: Если kubectl работает, экспортируйте текущее состояние
kubectl get nodes -o yaml > nodes-state.yaml
kubectl get pods -A -o yaml > pods-state.yaml

# Вариант 3: Полное восстановление с мастер-узла
ssh user@master-node "sudo cp /etc/kubernetes/ssl/* /path/to/backup/"
# Скопируйте сертификаты и восстановите cluster.rkestate из резервной копии

# Вариант 4: Если cluster.rkestate утерян безвозвратно
# Кластер продолжает работать, но RKE CLI не может им управлять
# Решение: импортируйте кластер в Rancher или пересоздайте через rke up
```

### Проблемы с Docker

```bash
# Проверка версии Docker (RKE требует特定ную версию)
ssh user@node "docker --version"
# → Docker version 24.0.7, build afdd53b

# Проверка статуса Docker
ssh user@node "systemctl status docker"
# → ● docker.service - Docker Application Container Engine
#    Loaded: loaded
#    Active: active (running) since ...

# Проверка места на диске для Docker
ssh user@node "docker system df"
# → TYPE            TOTAL     ACTIVE      SIZE      RECLAIMABLE
# → Images          15        12          2.1GB     500MB (23%)
# → Containers      12        12          150MB     0B (0%)
# → Local Volumes   8         8           1.2GB     0B (0%)
# → Build Cache     0         0           0B        0B

# Очистка неиспользуемых образов и контейнеров
ssh user@node "docker system prune -af"
# → Deleted Images:
# → ...
# → Total reclaimed space: 500MB
```

## Рекомендации по безопасности

### Защита файлов конфигурации

```bash
# Установка прав доступа на файлы конфигурации
chmod 600 cluster.yml cluster.rkestate kube_config_cluster.yml

# Проверка прав
ls -la *.yml *.rkestate
# → -rw------- 1 user user  2543 Aug  7 12:00 cluster.yml
# → -rw------- 1 user user  8921 Aug  7 12:00 cluster.rkestate
# → -rw------- 1 user user  2543 Aug  7 12:00 kube_config_cluster.yml
```

### SSH-безопасность

```bash
# Используйте отдельный ключ для RKE (не общий ключ)
ssh-keygen -t ed25519 -f ~/.ssh/rke_key -C "rke-admin"

# Добавьте публичный ключ на каждый узел
ssh-copy-id -i ~/.ssh/rke_key.pub user@node-ip

# Ограничьте права пользователя
# Пользователь для RKE должен быть в группе docker, но НЕ в группе sudo
ssh user@node "id -nG"
# → docker
```

### Сетевая безопасность

```bash
# Ограничьте доступ к порту API-сервера (6443)
# Только доверенные подсети должны иметь доступ
sudo iptables -A INPUT -p tcp --dport 6443 -s 192.168.1.0/24 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 6443 -j DROP

# Проверка правил
sudo iptables -L INPUT -n | grep 6443
# → ACCEPT     tcp  --  192.168.1.0/24    0.0.0.0/0    tcp dpt:6443
# → DROP       tcp  --  0.0.0.0/0         0.0.0.0/0    tcp dpt:6443
```

## Автоматизация и скрипты

### Шаблон скрипта для автоматического резервного копирования

```bash
#!/bin/bash
# /usr/local/bin/rke-backup.sh
# Автоматическое резервное копирование etcd для RKE кластера

set -euo pipefail

CLUSTER_DIR="/opt/rke-cluster"
BACKUP_DIR="/opt/rke-backups"
RETENTION_DAYS=7
DATE=$(date +%F-%H%M)
LOG_FILE="/var/log/rke-backup.log"

# Функция логирования
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Создание директории для бэкапов
mkdir -p "$BACKUP_DIR"

# Переход в директорию кластера
cd "$CLUSTER_DIR"

# Создание снимка
log "Начало создания снимка etcd..."
rke etcd snapshot-save --name "backup-${DATE}" --config cluster.yml 2>&1 | tee -a "$LOG_FILE"

# Копирование снимка в локальную директорию
log "Копирование снимка в локальную директорию..."
for node in $(grep -oP 'address: \K[0-9.]+' cluster.yml); do
    scp "user@${node}:/opt/rke/etcd-snapshots/backup-${DATE}" "${BACKUP_DIR}/" 2>/dev/null || true
done

# Удаление старых снимков
log "Очистка снимков старше ${RETENTION_DAYS} дней..."
find "$BACKUP_DIR" -name "backup-*" -mtime +${RETENTION_DAYS} -delete

# Проверка размера бэкапов
BACKUP_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/backup-* 2>/dev/null | wc -l)
log "Всего бэкапов: ${BACKUP_COUNT}, общий размер: ${BACKUP_SIZE}"

log "Резервное копирование завершено успешно."
```

```bash
# Установка выполнения скрипта
chmod +x /usr/local/bin/rke-backup.sh

# Добавление в cron (каждый день в 2:00)
echo "0 2 * * * /usr/local/bin/rke-backup.sh" | crontab -

# Проверка
crontab -l
# → 0 2 * * * /usr/local/bin/rke-backup.sh
```

### Шаблон скрипта для проверки здоровья кластера

```bash
#!/bin/bash
# /usr/local/bin/rke-healthcheck.sh
# Проверка здоровья RKE кластера

set -euo pipefail

KUBECONFIG="/path/to/kube_config_cluster.yml"
LOG_FILE="/var/log/rke-healthcheck.log"
ALERT_EMAIL="admin@example.com"

export KUBECONFIG

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

ERRORS=0

# 1. Проверка доступности API
if ! kubectl cluster-info > /dev/null 2>&1; then
    log "ОШИБКА: API-сервер недоступен!"
    ERRORS=$((ERRORS + 1))
else
    log "OK: API-сервер доступен"
fi

# 2. Проверка статуса узлов
NOT_READY_NODES=$(kubectl get nodes --no-headers | grep -v "Ready" | wc -l)
if [ "$NOT_READY_NODES" -gt 0 ]; then
    log "ОШИБКА: ${NOT_READY_NODES} узлов не в состоянии Ready"
    kubectl get nodes | grep -v "Ready" | tee -a "$LOG_FILE"
    ERRORS=$((ERRORS + 1))
else
    log "OK: Все узлы в состоянии Ready"
fi

# 3. Проверка подов в ошибочном ст態е
BAD_PODS=$(kubectl get pods -A --no-headers | grep -E 'CrashLoopBackOff|Error|ImagePullBackOff|Evicted' | wc -l)
if [ "$BAD_PODS" -gt 0 ]; then
    log "ОШИБКА: ${BAD_PODS} подов в ошибочном статусе"
    kubectl get pods -A | grep -E 'CrashLoopBackOff|Error|ImagePullBackOff|Evicted' | tee -a "$LOG_FILE"
    ERRORS=$((ERRORS + 1))
else
    log "OK: Все поды в нормальном статусе"
fi

# 4. Проверка etcd
if ! kubectl get --raw /healthz/etcd > /dev/null 2>&1; then
    log "ОШИБКА: etcd недоступен!"
    ERRORS=$((ERRORS + 1))
else
    log "OK: etcd доступен"
fi

# 5. Отправка алерта при ошибках
if [ "$ERRORS" -gt 0 ]; then
    log "ОБНАРУЖЕНО ${ERRORS} ОШИБОК!"
    # Отправка email (опционально)
    # echo "Обнаружено ${ERRORS} ошибок в RKE кластере. См. ${LOG_FILE}" | mail -s "RKE Health Alert" "$ALERT_EMAIL"
else
    log "Все проверки пройдены успешно."
fi
```

## Состав файлов состояния

| Файл | Назначение | Где хранится | Кто обновляет |
| :--- | :--- | :--- | :--- |
| **cluster.yml** | Декларативная конфигурация кластера (желаемое состояние) | Локальная машина / CI/CD | Администратор вручную |
| **cluster.rkestate** | Текущее состояние кластера (сертификаты, ключи, версии) | Локальная машина + узлы | RKE CLI автоматически |
| **kube_config_cluster.yml** | Файл доступа для kubectl (секреты) | Локальная машина | RKE CLI автоматически |

> [!IMPORTANT]
> Файлы `cluster.rkestate` и `kube_config_cluster.yml` содержат критически важные секреты (приватные ключи TLS). Никогда не храните их в git-репозиториях и всегда устанавливайте права доступа `chmod 600`.

## Важные ограничения RKE1

*   **Docker Only**: RKE1 не поддерживает containerd напрямую — все компоненты запускаются как Docker-контейнеры. Это ключевое отличие от Kubespray и RKE2.
*   **SSH Latency**: При плохом соединении между машиной с RKE CLI и узлами возможны таймауты при развертывании. Рекомендуется использовать локальную сеть или VPN с низкой задержкой.
*   **Нет автомасштабирования**: Все операции масштабирования выполняются вручную через правку `cluster.yml` и `rke up`.
*   **Единый файл конфигурации**: Вся конфигурация кластера хранится в одном файле `cluster.yml`. Для управления несколькими кластерами используйте разные директории или разные имена файлов.
*   **EOL**: RKE1 достиг конца жизненного цикла 31 июля 2025 года. Новые функции не добавляются, выпускаются только критические патчи.

## Дополнительные темы для эксплуатации

Ниже перечислены темы, необходимые для полноценной эксплуатации RKE-кластера в production.

### Мониторинг и алертинг

RKE не включает мониторинг «из коробки». Metrics Server (для HPA) устанавливается автоматически, но для полноценного мониторинга необходим стек Prometheus + Grafana.

* Установка через Helm: [kube-prometheus-stack: Обзор](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md)
* Prometheus Operator (CRDs): [Prometheus Operator: Концепции](../../../Prometheus/kubernetes/operator/concepts.md)
* Grafana дашборды: [Grafana: Kubernetes Alerting](../../../Grafana/alerting/kubernetes_alerts.md)
* Alertmanager: [Alertmanager](../../../Prometheus/alertmanager.md)
* Прометей + Kubernetes: [Prometheus на Kubernetes](../../../Prometheus/kubernetes/overview.md)
* SLI/SLO: [SLI/SLO в Kubernetes](../../../Kubernetes/Networking/gateway_api/monitoring.md)

### Сбор и агрегация логов

Для централизованного сбора логов с узлов и подов RKE используйте DaemonSet-based решения.

* **Loki + Promtail/Alloy** (рекомендуется): [Loki: Обзор](../../../Loki/loki_overview.md), [Установка Loki](../../../Loki/loki_stack_setup/loki_installation.md), [Alloy с Loki](../../../Loki/loki_stack_setup/alloy_installation.md)
* **EFK Stack** (Elasticsearch + Fluentd/Fluent Bit): [EFK Setup](../../../Kubernetes/MonitoringLogging/EFK/efk_stack_setup_guide.md)
* **Fluent Bit** (lightweight): [Fluent Bit Configuration](../../../Kubernetes/MonitoringLogging/EFK/fluentbit/fluentbit_configuration.md)
* Архитектура мониторинга + логов: [K8s Monitoring/Logging Architecture](../../../Kubernetes/MonitoringLogging/kubernetes-monitoring-logging-architecture.md)

### Secrets Management

Kubernetes Secrets хранятся в etcd в открытом виде (без шифрования по умолчанию). Для production используйте внешние менеджеры секретов.

* **HashiCorp Vault + K8s интеграция**: [Vault + Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md)
* **Vault Agent Injector (sidecar)**: [Vault Agent Injector](../../../Vault/guides/vault_agent/injector.md)
* **Sealed Secrets** (для GitOps): [Sealed Secrets](../../../Kubernetes/Security/sealed_secrets_overview.md)
* **External Secrets Operator**: [ESO](../../../Kubernetes/Base/secrets/external_managers.md)
* **Шифрование etcd**: [Secrets: Шифрование в etcd](../../../Kubernetes/Base/secrets/etcd_storage.md)
* **helm-secrets + SOPS**: [Helm Secrets](../../../Kubernetes/Base/secrets/helm_secrets.md)

### GitOps (ArgoCD, Flux)

Декларативный деплой через Git — стандарт для production Kubernetes.

* **ArgoCD**: [ArgoCD: Обзор](../../../GitOps/ArgoCD/argocd_overview.md), [Установка](../../../GitOps/ArgoCD/argocd_installation_and_setup.md), [Синхронизация](../../../GitOps/ArgoCD/synchronization.md)
* **Flux**: [Flux CD](../../../GitOps/flux.md)
* **Сравнение ArgoCD vs Flux**: [ArgoCD vs Flux](../../../GitOps/argo_vs_flux_manifests.md)
* **GitOps Pipeline**: [GitOps Pipeline Example](../../../GitOps/gitops_pipeline_example.md)
* **Secrets в GitOps**: [Secrets Encryption](../../../GitOps/secrets_encryption.md)

### Продвинутый troubleshooting

Для системного подхода к поиску неисправностей:

* Методология: [Troubleshooting: Обзор](../../Troubleshooting/troubleshooting_overview.md)
* CrashLoopBackOff: [Диагностика](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/)
* Pod Pending: [Диагностика](../../Troubleshooting/Common_Errors/pod_pending/)
* OOMKilled: [Анализ](../../Troubleshooting/Common_Errors/oomkilled_pods.md)
* CPU Throttling: [CPU Throttling](../../Troubleshooting/Common_Errors/cpu_throttling.md)
* Node Unavailability: [Node Issues](../../Troubleshooting/Common_Errors/NodeUnavailability/)
* RBAC ошибки: [Forbidden/Denied](../../Troubleshooting/Common_Errors/ApiAccessForbidden/)

---

**См. также:**
* [RKE: Основные концепции](./rke_concepts.md)
* [RKE: Высокая доступность](./rke_high_availability.md)
* [RKE: Установка kubectl и настройка доступа](./rke_kubectl_setup.md)
