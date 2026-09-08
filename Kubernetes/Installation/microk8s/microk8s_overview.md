# MicroK8s: обзор и архитектура

## Определения

**MicroK8s** — сертифицированный CNCF легковесный дистрибутив Kubernetes от компании Canonical. Представляет собой полноценный upstream-кластер (zero-ops), упакованный в Snap-пакет с изолированными компонентами и встроенной системой аддонов.

Ключевой особенностью современных версий является **Strict Confinement** (строгая изоляция) — режим работы, при котором кластер полностью изолирован от хостовой файловой системы, что делает его одним из самых безопасных решений для Edge-вычислений и IoT.

**Kubelite** — облегчённый бинарный файл, объединяющий kube-apiserver, kube-controller-manager, kube-scheduler и kube-proxy в единый процесс. Используется в MicroK8s по умолчанию вместо отдельных компонентов Control Plane, что снижает потребление памяти и упрощает эксплуатацию.

### Ключевые отличия

- **Упаковка:** Snap-пакет — каждый компонент работает как отдельный процесс, управляемый через snapd, со своими зависимостями.
- **Хранилище:** по умолчанию используется **DQLite** — распределённая БД на основе SQLite с алгоритмом Raft, заменяющая тяжеловесный `etcd`. Подробная информация о DQLite и других альтернативах etcd — в [etcd: альтернативы и безопасность](../../Concepts/etcd_alternatives_and_security.md).
- **Интеграция:** нативная поддержка Ubuntu и других дистрибутивов с поддержкой Snap (Debian, CentOS, Fedora, RHEL, openSUSE, Arch). Поддерживает x86_64 и ARM (Raspberry Pi, NVIDIA Jetson).
- **Zero-Ops:** автоматические обновления (через каналы snap) и минимальные усилия на поддержку жизненного цикла.
- **Кроссплатформенность:** помимо Linux, доступны инсталляции для Windows (через Multipass или WSL2) и macOS (через Multipass или MicroK8s Dedicated).

---

## Предварительные требования

### Аппаратные требования

| Ресурс | Минимум | Рекомендуется (Production/Edge) |
|:-------|:--------|:-------------------------------|
| RAM | 2 ГБ | 4+ ГБ |
| CPU | 2 ядра | 4+ ядра |
| Диск | 20 ГБ | 50+ ГБ |
| Сеть | 1 NIC | 1 NIC, статический IP (для HA) |

*Примечание: Из-за оверхеда Snap и раздельных процессов MicroK8s потребляет больше памяти, чем K3s. Для устройств с <2 ГБ RAM лучше использовать K3s.*

### Программные зависимости

- **ОС:** Ubuntu 20.04+, Debian 11+, CentOS/RHEL 8+, Fedora 36+, openSUSE Leap 15.4+, Arch Linux
- **Snapd:** должен быть установлен и активирован (`snap version`)
- **Ядро Linux:** 4.4+ (рекомендуется 5.4+ для полной поддержки cgroups v2)
- **Сеть:** открытые порты: 16443 (API Server), 10250 (kubelet), 10255 (kubelet read-only), 25000 (dqlite), 19001 (cluster agent)

### Поддержка платформ

| Платформа | Метод установки | Примечания |
|:----------|:----------------|:-----------|
| **Ubuntu** | `snap install microk8s --classic` | Нативная поддержка, рекомендуется |
| **Debian** | `snap install microk8s --classic` | Требуется `snapd` из repos |
| **CentOS/RHEL 8+** | `snap install microk8s --classic` | Требуется `snapd` |
| **Fedora** | `snap install microk8s --classic` | Требуется `snapd` |
| **macOS** | Multipass + MicroK8s | Виртуализация через Multipass |
| **Windows** | Multipass + MicroK8s или WSL2 | Рекомендуется Multipass для полного функционала |

---

## Основные концепции

### Архитектура и компоненты

MicroK8s максимально близок к стандартной архитектуре Kubernetes. В отличие от K3s, где всё упаковано в один бинарный файл, MicroK8s по умолчанию использует **Kubelite** — объединённый бинарник Control Plane, но при необходимости может работать и с отдельными компонентами.

#### Компоненты Control Plane

- **Kube-apiserver (Kubelite):** точка входа для всех REST-вызовов. В режиме Kubelite интегрирован с kube-controller-manager и kube-scheduler.
- **DQLite (Distributed SQLite):** обеспечивает высокую доступность без внешнего etcd. Кластер из 3+ узлов автоматически переходит в режим HA с кворумом. Подробнее: [etcd: альтернативы и безопасность](../../Concepts/etcd_alternatives_and_security.md#альтернативы-etcd-kine-и-распределенные-бд).
- **Containerd:** стандартный рантайм контейнеров, управляемый через snap. Работает в изолированном пространстве имён.

#### Компоненты Worker Node

- **Kubelet:** агент узла, управляемый через snap.
- **Containerd:** рантайм контейнеров с CRI-интерфейсом.
- **CNI:** по умолчанию **Calico** (supports NetworkPolicy). Доступны альтернативы через аддоны: Cilium (eBPF), Flannel.

#### Дополнительные компоненты

- **Cluster API (CAPI):** поддержка автоматизированного управления жизненным циклом кластеров.
- **GPU/FPGA:** встроенная поддержка ускорения для задач ИИ через аддон `nvidia` (NVIDIA GPU Operator).
- **Helm 3:** встроен как `microk8s helm3` для управления.chart-пакетами.

### Высокая доступность (High Availability)

Режим HA включается автоматически при объединении **3 и более узлов**.

- **Кворум:** DQLite динамически распределяет роли (Voter, Standby). При выходе из строя одного Voter-узла, его роль берёт на себя Standby. Требуется нечётное количество узлов (3, 5, 7) для формирования кворума.
- **Zero-config:** не требуется настройка внешних балансировщиков для Control Plane внутри самого кластера.
- **Автовосстановление:** при потере узла DQLite автоматически перераспределяет данные между оставшимися узлами.
- **Ограничение:** Maximum Pod count на узле — 110 (стандартное ограничение kubelet). Для HA-кластеров рекомендуется минимум 3 узла с 4+ CPU и 8+ RAM каждый.

### Безопасность

#### RBAC

- По умолчанию **включён** в современных версиях MicroK8s (1.25+). В ранних версиях мог быть выключен — рекомендуется проверять после установки: `microk8s kubectl auth can-i --list`.
- Аутентификация через x509-сертификаты (стандарт Kubernetes).

#### Strict Confinement

- Предотвращает доступ скомпрометированных подов к ядру или файлам хоста за пределами разрешенных интерфейсов.
- Snap-пакет работает в изолированном namespace, компоненты не имеют прямого доступа к `/etc`, `/var` хоста (кроме явно разрешенных путей).
- Включается флагом `--strict` при установке: `snap install microk8s --strict --channel=1.35/stable`.

#### CIS Hardening

- MicroK8s соответствует рекомендациям CIS Kubernetes Benchmark.
- Некоторые параметры hardened по умолчанию: аутентификация через x509 (не токены), настройки audit logging.
- Инструкции по ручному ужесточению: [microk8s.io/docs/how-to-cis-harden](https://microk8s.io/docs/how-to-cis-harden).

#### AppArmor

- MicroK8s включает профиль AppArmor по умолчанию, ограничивающий доступ контейнеров к системным ресурсам.
- Профиль обновляется при каждом snap refresh.

#### Сетевые политики

- По умолчанию **Calico** (поддержка NetworkPolicy из коробки).
- Альтернативы: **Cilium** (eBPF, L7-политики), **Flannel** (без поддержки NetworkPolicy).
- Для реализации модели "Zero Trust" рекомендуется Calico или Cilium с Default-Deny политикой.

### Требования к ресурсам

| Ресурс | Минимум | Рекомендуется (Production/Edge) |
|:-------|:--------|:-------------------------------|
| RAM | 2 ГБ | 4+ ГБ |
| CPU | 2 ядра | 4+ ядра |
| Диск | 20 ГБ | 50+ ГБ |

*Примечание: Из-за оверхеда Snap и раздельных процессов MicroK8s потребляет больше памяти, чем K3s. Для устройств с <2 ГБ RAM лучше использовать K3s.*

---

## Система аддонов

Аддоны позволяют подключать сложные компоненты одной командой. Они разделены на:

1. **Core:** официально поддерживаемые Canonical (dns, ingress, rbac, storage, helm3, metallb, cert-manager, community).
2. **Community:** поддерживаемые сообществом (argocd, istio, keda, observability, prometheus, rook-ceph, longhorn).

### Доступные аддоны

| Аддон | Назначение | Режим по умолчанию |
|:------|:-----------|:-------------------|
| **dns** | CoreDNS для сервис-дискавери | Автоматически при объединении узлов |
| **ingress** | NGINX Ingress Controller | Manual |
| **rbac** | Role-Based Access Control | Включён (1.25+) |
| **storage** | Hostpath storage class | Manual |
| **helm3** | Helm 3包管理щик | Manual |
| **metallb** | LoadBalancer для bare-metal | Manual |
| **cert-manager** | Управление TLS-сертификатами | Manual |
| **community** | Community-аддоны | Manual |
| **observability** | Prometheus + Grafana | Manual |
| **prometheus** | Стэк мониторинга | Manual |
| **longhorn** | Распределённое хранилище | Manual |
| **rook-ceph** | Ceph-хранилище | Manual |
| **istio** | Service Mesh | Manual |
| **argocd** | GitOps оператор | Manual |
| **keda** | Autoscaling по событиям | Manual |
| **nvidia** | GPU-поддержка | Manual |

```bash
# Список всех доступных аддонов
microk8s status

# Включение необходимых компонентов для продакшена
microk8s enable dns rbac ingress observability helm3

# Включение с конкретными параметрами
microk8s enable metallb:10.64.140.43-10.64.140.49

# Проверка статуса конкретного аддона
microk8s status --yaml | grep -A5 dns

# Отключение аддона
microk8s disable <addon-name>
```

---

## Практические сценарии

### Установка и базовая настройка

Рекомендуется использовать конкретный канал для фиксации версии Kubernetes.

```bash
# Установка конкретной версии (например, 1.35)
sudo snap install microk8s --classic --channel=1.35/stable

# Установка latest (1.36 на момент написания)
sudo snap install microk8s --classic

# Настройка прав (выполняется один раз)
sudo usermod -a -G microk8s $USER
mkdir -p ~/.kube
chmod 0700 ~/.kube
newgrp microk8s

# Создание алиаса для kubectl
snap alias microk8s.kubectl kubectl

# Проверка установки
microk8s status --wait-ready
```

#### Ожидаемый вывод `microk8s status`

```
microk8s is running
high-availability: no
  datastore master nodes: 127.0.0.1:19001
  datastore standby nodes: none
        Addons:
          dashboard: disabled
          dns: disabled
          helm3: disabled
          ...
```

### Управление кластером

```bash
# Проверка состояния HA и аддонов
microk8s status

# Остановка/Запуск (полезно для экономии ресурсов на ноутбуке)
microk8s stop
microk8s start

# Генерация конфига для внешних инструментов (Lens, kubectl)
microk8s config > ~/.kube/config

# Диагностика кластера (собирает логи и системную информацию)
microk8s inspect

# Просмотр логов конкретного компонента
microk8s logs --revision=-1 | grep kube-apiserver
microk8s logs --revision=-1 | grep kubelet

# Просмотр логов через journalctl
sudo journalctl -u snap.microk8s.daemon-kubelite -f
sudo journalctl -u snap.microk8s.daemon-containerd -f
```

### Создание HA-кластера

1. На **первом** узле: `microk8s add-node`.
2. Скопировать команду `microk8s join ...` из вывода (содержит token и IP-адрес).
3. На **втором и третьем** узлах: выполнить скопированную команду.
4. Проверить статус: `microk8s status` должен показать `high-availability: yes`.

```bash
# Проверка кворума
microk8s kubectl get nodes -o wide

# Проверка состояния DQLite
microk8s kubectl -n kube-system logs deploy/dqlite-k8s-ds --tail=50

# Добавление узла в HA-кластер (на любом существующем узле)
microk8s add-node

# Удаление узла из кластера (на удаляемом узле)
microk8s leave

# Принудительное удаление узла (на любом работоспособном узле)
microk8s remove-node <node-name>
```

### Управление версиями и обновления (Lifecycle Management)

```bash
# Просмотр доступных каналов
snap find microk8s

# Переход на новую минорную версию (например, с 1.34 на 1.35)
sudo snap refresh microk8s --channel=1.35/stable

# Обновление в рамках текущего канала (патч-выпуски)
sudo snap refresh microk8s

# Просмотр последних обновлений
snap changes | grep microk8s

# Откат версии (в рамках snap)
sudo snap revert microk8s

# Блокировка обновлений (hold)
sudo snap hold microk8s

# Разблокировка обновлений
sudo snap unhold microk8s

# Настройка расписания обновлений (глобально для всех snap)
sudo snap set system refresh.timer=fri5,22:00-23:00
```

#### Порядок обновления минорных версий

1. **Прочитать release notes** целевой версии на [microk8s.io/docs/release-notes](https://microk8s.io/docs/release-notes).
2. **Бэкап:** `microk8s kubectl get --all-namespaces -o yaml > backup.yaml` + бэкап DQLite.
3. **Обновить Control Plane:** `sudo snap refresh microk8s --channel=<new-version>/stable`.
4. **Проверить:** `microk8s status --wait-ready`, `microk8s kubectl get nodes`.
5. **Обновить addons:** `microk8s disable <addon> && microk8s enable <addon>` (при необходимости).
6. **Обновить worker-узлы:** по одному, сначала cordone/drain, потом обновление.

### Работа в закрытом контуре (Air-gapped)

1. **Скачивание:** на машине с интернетом: `snap download microk8s`.
2. **Перенос:** скопировать `.snap` и `.assert` файлы на целевой сервер.
3. **Установка:** `snap ack microk8s.assert && snap install microk8s.snap --classic`.
4. **Образы:** импорт образов во внутренний реестр: `microk8s ctr image import my-image.tar`.

```bash
# На машине с интернетом
snap download microk8s --channel=1.35/stable

# Перенос файлов
scp microk8s_*.snap microk8s_*.assert user@target-server:/tmp/

# На целевом сервере
cd /tmp
sudo snap ack microk8s_*.assert
sudo snap install microk8s_*.snap --classic

# Импорт образов (если есть локальный реестр)
microk8s ctr images pull registry.example.com/myimage:latest
# Или из tar-архива
microk8s ctr images import my-image.tar
```

### Настройка сетевой подсистемы

```bash
# По умолчанию MicroK8s использует Calico
# Проверка CNI
microk8s kubectl get pods -n kube-system | grep calico

# Переключение на Cilium (eBPF)
microk8s disable calico
microk8s enable cilium

# Настройка MetalLB для LoadBalancer-сервисов
microk8s enable metallb:10.64.140.43-10.64.140.49

# Проверка NetworkPolicy
microk8s kubectl get networkpolicy --all-namespaces

# Пример NetworkPolicy (Default Deny)
cat <<EOF | microk8s kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: default
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
EOF
```

### Настройка хранилища

```bash
# Включение storage-аддона (hostpath)
microk8s enable storage

# Проверка StorageClass
microk8s kubectl get sc

# Longhorn для распределённого хранилища
microk8s enable longhorn

# Rook-Ceph для production-хранилища
microk8s enable rook-ceph

# Создание PVC
cat <<EOF | microk8s kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: microk8s-hostpath
  resources:
    requests:
      storage: 10Gi
EOF
```

### Настройка мониторинга

```bash
# Включение стека observability (Prometheus + Grafana)
microk8s enable observability

# Проверка компонентов
microk8s kubectl get pods -n observability

# Доступ к Grafana
microk8s kubectl -n observability port-forward svc/grafana 3000:80

# Доступ к Prometheus
microk8s kubectl -n observability port-forward svc/prometheus-k8s 9090:9090

# Проверка метрик
curl -s http://localhost:9090/api/v1/query?query=up
```

### Резервное копирование и восстановление

```bash
# Бэкап всех ресурсов кластера
microk8s kubectl get --all-namespaces -o yaml > microk8s-backup-$(date +%Y%m%d).yaml

# Бэкап DQLite (на HA-кластере)
sudo cp /var/snap/microk8s/current/var/kubernetes/backend/cockroachdb.snapshot ~/dqlite-backup-$(date +%Y%m%d)

# Бэкап Sercrets (требует доступа к etcd/dqlite)
microk8s kubectl get secrets --all-namespaces -o yaml > secrets-backup-$(date +%Y%m%d).yaml

# Восстановление из манифеста
microk8s kubectl apply -f microk8s-backup.yaml

# Полный сброс кластера (УДАЛЯЕТ ВСЕ ДАННЫЕ)
microk8s reset
```

---

## Диагностика и типовые ошибки

### Общая диагностика

```bash
# Комплексная диагностика (собирает логи, конфиги, системную информацию)
microk8s inspect

# Проверка состояния всех snap-сервисов
microk8s status

# Проверка логов (последние 100 строк)
microk8s logs --tail=100

# Проверка конкретного пода
microk8s kubectl describe pod <pod-name> -n <namespace>

# Проверка событий кластера
microk8s kubectl get events --all-namespaces --sort-by='.lastTimestamp'
```

### Типовые ошибки

**Ошибка: `error: unable to recognize ... no matches for kind`**
- **Причина:** API-ресурс не зарегистрирован или отсутствует в кластере.
- **Решение:** `microk8s kubectl api-resources` — проверить доступные ресурсы. Убедиться, что нужный аддон включён.

**Ошибка: `The connection to the server was refused`**
- **Причина:** API-сервер не запущен или kubeconfig настроен неправильно.
- **Решение:**
  ```bash
  microk8s status          # проверить, что microk8s is running
  microk8s inspect         # собрать диагностику
  sudo journalctl -u snap.microk8s.daemon-kubelite -n 50
  ```

**Ошибка: `Unable to connect to the server: x509: certificate has expired`**
- **Причина:** Сертификаты Control Plane истекли.
- **Решение:**
  ```bash
  sudo snap restart microk8s
  # Если не помогло — сброс и восстановление
  microk8s reset
  ```

**Ошибка: `microk8s kubectl get pods` показывает `Pending` для всех подов**
- **Причина:** CNI не работает, kubelet не может создать поды.
- **Решение:**
  ```bash
  microk8s kubectl get pods -n kube-system | grep -E "calico|cilium|flannel"
  microk8s kubectl logs -n kube-system <cni-pod>
  sudo journalctl -u snap.microk8s.daemon-containerd -n 50
  ```

**Ошибка: `dqlite` кластер не формирует кворум (HA)**
- **Причина:** Сетевая связность между узлами нарушена, firewall блокирует порт 25000.
- **Решение:**
  ```bash
  # Проверка сетевой связности
  nc -zv <other-node-ip> 25000
  # Проверка статуса DQLite
  microk8s kubectl -n kube-system logs deploy/dqlite-k8s-ds --tail=50
  # Проверка firewall
  sudo iptables -L -n | grep 25000
  ```

**Ошибка: `microk8s enable` завершается с ошибкой**
- **Причина:** Зависимости аддона не установлены, нет доступа к интернету.
- **Решение:**
  ```bash
  microk8s inspect          # проверить логи
  sudo snap refresh microk8s  # обновить snap
  # Для air-gapped: убедиться, что образы доступны в локальном реестре
  ```

**Ошибка: kubelet не запускается после `microk8s start`**
- **Причина:** Повреждённые данные или конфликт с другими CNI.
- **Решение:**
  ```bash
  sudo journalctl -u snap.microk8s.daemon-kubelet -n 50
  sudo snap stop microk8s
  sudo rm -rf /var/snap/microk8s/current/var/kubernetes/
  sudo snap start microk8s
  # ПРИМЕЧАНИЕ: это удалит все данные кластера
  ```

---

## Best Practices

### Установка и начальная настройка

- **Фиксируйте версию:** Всегда указывайте канал при установке (`--channel=1.35/stable`), не используйте `latest` в production.
- **Настраивайте права:** Добавляйте пользователя в группу `microk8s` сразу после установки.
- **Создавайте алиасы:** `snap alias microk8s.kubectl kubectl` для удобства работы.
- **Включайте RBAC:** Проверяйте включение: `microk8s kubectl auth can-i --list`.

### Безопасность

- **RBAC обязателен:** Не отключайте RBAC даже в dev-среде — это формирует привычку.
- **NetworkPolicy:** Включайте Default-Deny политики для изоляции подов.
- **Обновления:** Не блокируйте snap-обновления дольше 30 дней — критические патчи безопасности выходят регулярно.
- **CIS Hardening:** Для production следуйте рекомендациям CIS Kubernetes Benchmark.
- **Secrets:** Используйте external-secrets или vault-integration вместо plaintext Secret в манифестах.

### Производительность

- **Ресурсы:** Всегда задавайте `requests` и `limits` для подов.
- **Мониторинг:** Включайте `observability` или `prometheus` для отслеживания использования ресурсов.
- **DQLite:** Для HA-кластеров используйте нечётное количество узлов (3, 5, 7).
- **Диск:** Используйте SSD для DQLite и containerd — это критично для производительности.

### Эксплуатация

- **Бэкапы:** Регулярно выполняйте `microk8s kubectl get --all-namespaces -o yaml > backup.yaml`.
- **Логирование:** Настройте централизованное логирование (Loki, ELK) до возникновения проблем.
- **Обновления:** Обновляйте по одной минорной версии, читайте release notes.
- **Тестирование:** Тестируйте обновления на staging перед применением в production.
- **Документирование:** Фиксируйте уникальные настройки кластера (аддоны, NetworkPolicy, StorageClass).

### Air-gapped среды

- **Подготовка:** Скачайте все необходимые заранее: snap-пакеты, Docker-образы, Helm-чарты.
- **Реестр:** Настройте локальный registry (`microk8s enable registry`) или внешний (Harbor).
- **Обновления:** Процесс обновления в air-gapped сложнее — планируйте заранее.

---

## Дополнительная информация

### Сравнение с K3s

| Параметр | MicroK8s | K3s |
|:---------|:---------|:----|
| **Метод поставки** | Snap-пакет | Одиночный бинарный файл |
| **Изоляция** | Strict Confinement (опционально) | Стандартная Linux изоляция |
| **Хранилище** | DQLite (Native HA) | SQLite (Kine) или etcd |
| **Control Plane** | Kubelite (объединённый) или отдельные процессы | Единый процесс-агрегатор |
| **Управление** | Встроенные аддоны (`enable`) | Авто-деплой манифестов / Helm |
| **CNI по умолчанию** | Calico | Flannel |
| **Minimal RAM** | 2 ГБ | 512 МБ |
| **ARM поддержка** | x86_64, ARM | x86_64, ARM, ARMv7 |
| **Версия (stable, авг 2026)** | 1.35 | 1.36 |

### Когда выбирать MicroK8s

- **Ubuntu-инсталляция:** Snap-пакет обеспечивает наилучшую интеграцию с Ubuntu.
- **HA без etcd:** DQLite проще в обслуживании, чем etcd.
- **Безопасность:** Strict Confinement и AppArmor из коробки.
- **GPU-задачи:** Встроенная поддержка NVIDIA через аддон.
- **Canonical-экосистема:** Интеграция с Juju, MAAS, Landscape.

### Когда выбирать K3s

- **Минимальные ресурсы:** K3s потребляет в 4+ раза меньше RAM.
- **ARM/IoT:** K3s поддерживает ARMv7 (Raspberry Pi Zero).
- **Простота:** Единый бинарный файл, без snap-зависимости.
- **Helm-first:** Автоматический деплой Helm-чартов из `/var/lib/rancher/k3s/server/manifests/`.

### См. также

- [K3s: архитектура dev-окружения](../k3s_dev_environment/k3s_architecture.md)
- [Minikube: концепции и архитектура](../minikube/minikube_concepts.md)
- [kind: запуск K8s в Docker](../kind/kind_concepts.md)
- [etcd: альтернативы и безопасность](../../Concepts/etcd_alternatives_and_security.md)
- [Критерии выбора платформы](../../Concepts/platform_selection_criteria.md)
- [Container Runtime в Kubernetes](../../Concepts/container_runtime.md)
