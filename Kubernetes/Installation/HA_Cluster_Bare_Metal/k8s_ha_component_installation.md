# Установка компонентов Kubernetes на узлы

## Определения

**containerd** — индустриальный стандарт среды выполнения контейнеров (Container Runtime), реализующий спецификацию CRI. В современных кластерах (K8s 1.24+) является основным движком, обеспечивающим высокую производительность за счет отсутствия лишних прослоек (Docker-shim).

**CRI (Container Runtime Interface)** — интерфейс, позволяющий `kubelet` взаимодействовать с различными средами выполнения контейнеров.

**kubeadm** — утилита для автоматизации жизненного цикла кластера (инициализация, обновление, управление токенами и сертификатами).

**kubelet** — основной агент узла, отвечающий за выполнение контейнеров и проверку их состояния (Health Checks).

**kubectl** — инструмент командной строки для взаимодействия с API-сервером Kubernetes.

**pause image (Sandbox Image)** — служебный контейнер, который «держит» сетевое пространство имен (Network Namespace) и IPC для пода. Все остальные контейнеры пода подключаются к его ресурсам.

**SystemdCgroup** — параметр конфигурации containerd, указывающий использовать `systemd` как драйвер cgroup. Обязателен в современных дистрибутивах для предотвращения конфликтов между kubelet и containerd при управлении ресурсами.

**cgroup v2** — современная подсистема ядра Linux для управления ресурсами контейнеров. Обеспечивает единую иерархию и предсказуемое потребление ресурсов. Обязательна для Kubernetes 1.25+.

---

## Основные концепции

### Роль Container Runtime в архитектуре узла

`containerd` — это «рабочая лошадка» кластера. Он отвечает за:
- Скачивание и хранение образов.
- Создание и запуск контейнеров через `runc`.
- Управление снимками файловой системы (Snapshots).
- Организацию сетевых интерфейсов через CNI.

Подробнее о типах рантаймов и их архитектуре: **[Container Runtime в Kubernetes](../../../Concepts/container_runtime.md)**.

### Иерархия компонентов и их связи

1. **kubelet** получает инструкции от API-сервера.
2. **kubelet** вызывает **containerd** через gRPC сокет (`/run/containerd/containerd.sock`).
3. **containerd** запускает контейнеры.
4. **kubeadm** настраивает конфигурацию для первых двух компонентов.

Подробнее о работе kubelet: **[Kubelet — агент Kubernetes](../../../Concepts/kubelet.md)**.

### Версионная совместимость (HA-кластер)

| Компонент | Версия | Критичность для HA |
| :--- | :--- | :--- |
| Kubernetes | v1.35.x | Все узлы должны иметь одинаковую минорную версию |
| containerd | v1.7+ / v2.0 | Разница до 3 минорных версий допустима |
| Linux Kernel | 5.15+ (рекомендуется 6.x) | Обязательна поддержка cgroup v2 |
| systemd | 245+ | Управляет ресурсами и автозагрузкой |

**Правило согласованности:** В HA-кластере версии `kubeadm`, `kubelet` и `kubectl` должны совпадать на **всех** узлах Control Plane и Worker. Несовпадение версий приводит к ошибкам при инициализации и присоединении узлов.

---

## Практические сценарии

### Шаг 1: Установка и базовая настройка containerd

Рекомендуется использовать официальный репозиторий Docker для получения актуальных версий `containerd` с поддержкой последних функций безопасности.

#### Ubuntu/Debian

```bash
# Установка необходимых пакетов
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Добавление GPG-ключа и репозитория
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y containerd.io
```

#### RHEL/Rocky Linux 9

```bash
# Добавление репозитория Docker
sudo dnf install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo

# Установка containerd
sudo dnf install -y containerd.io

# Проверка версии
containerd --version
# → containerd github.com/containerd/containerd v2.0.x ...
```

### Шаг 2: Глубокая конфигурация containerd (SSoT)

Критически важно использовать `SystemdCgroup = true`, так как в современных дистрибутивах Linux (Ubuntu 22.04+) `systemd` является менеджером ресурсов по умолчанию. Использование разных драйверов для `kubelet` и `containerd` приведет к нестабильности системы.

#### Генерация и оптимизация конфига

```bash
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml > /dev/null

# 1. Включение SystemdCgroup
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/g' /etc/containerd/config.toml

# 2. Настройка актуальной версии pause-образа (v1.35 требует 3.10)
# registry.k8s.io/pause:3.10 — текущий стандарт
sudo sed -i 's|sandbox_image = ".*"|sandbox_image = "registry.k8s.io/pause:3.10"|' /etc/containerd/config.toml

# 3. Настройка лимитов открытых файлов для рантайма
sudo mkdir -p /etc/systemd/system/containerd.service.d
cat <<EOF | sudo tee /etc/systemd/system/containerd.service.d/limits.conf
[Service]
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity
EOF

sudo systemctl daemon-reload
sudo systemctl restart containerd
sudo systemctl enable containerd
```

#### Настройка Registry Mirrors (для HA с локальным реестром)

В production-средах с ограниченным доступом к интернету или при использовании локального реестра (Harbor, Nexus):

```bash
# Редактирование /etc/containerd/config.toml
# Добавить в секцию [plugins."io.containerd.grpc.v1.cri".registry]:

# Пример: зеркало Docker Hub
# [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
#   endpoint = ["https://mirror.example.com"]

# Пример: локальный реестр с TLS
# [plugins."io.containerd.grpc.v1.cri".registry.configs."harbor.internal".tls]
#   ca_file = "/etc/containerd/certs/harbor-ca.crt"

sudo systemctl restart containerd
```

#### Настройка Garbage Collection

Для предотвращения переполнения диска неиспользуемыми образами:

```bash
# Проверка текущих настроек GC
containerd config dump | grep -A5 "gc"

# Включение автоматического удаления распакованных слоёв (экономия диска)
# В /etc/containerd/config.toml:
# [plugins."io.containerd.grpc.v1.cri".containerd]
#   discard_unpacked_layers = true
```

### Шаг 3: Настройка crictl для диагностики

`crictl` — это CLI для CRI-совместимых рантаймов. Его настройка обязательна для быстрой отладки.

```bash
cat <<EOF | sudo tee /etc/crictl.yaml
runtime-endpoint: unix:///run/containerd/containerd.sock
image-endpoint: unix:///run/containerd/containerd.sock
timeout: 10
debug: false
EOF

# Проверка:
sudo crictl ps
# → Должен вернуть пустой список (или список подов, если кластер уже запущен)
```

### Шаг 4: Установка kubeadm, kubelet, kubectl (v1.35)

Версии этих компонентов должны совпадать между собой. Мы используем новый формат репозиториев (pkgs.k8s.io).

#### Ubuntu/Debian

```bash
# Подготовка ключей
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.35/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# Добавление репозитория (v1.35)
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.35/deb/ /" | sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl

# Фиксация версий (Blocking Rule)
# Это предотвращает случайное обновление компонентов при apt upgrade
sudo apt-mark hold kubelet kubeadm kubectl

# Включение автозагрузки kubelet
sudo systemctl enable --now kubelet
```

#### RHEL/Rocky Linux 9

```bash
cat <<EOF | sudo tee /etc/yum.repos.d/kubernetes.repo
[kubernetes]
name=Kubernetes
baseurl=https://pkgs.k8s.io/core:/stable:/v1.35/rpm/
enabled=1
gpgcheck=1
gpgkey=https://pkgs.k8s.io/core:/stable:/v1.35/rpm/repodata/repomd.xml.key
EOF

sudo dnf install -y kubelet kubeadm kubectl --disableexcludes=kubernetes
sudo systemctl enable --now kubelet

# Проверка версий
kubeadm version -o short
kubelet --version
```

### Шаг 5: Проверка готовности узла к инициализации

```bash
echo "--- ПРОВЕРКА КОМПОНЕНТОВ ---"

# 1. Runtime
if systemctl is-active --quiet containerd; then
    echo "[OK] containerd активен"
else
    echo "[FAIL] containerd остановлен!"
fi

# 2. CRI Socket
if [ -S /run/containerd/containerd.sock ]; then
    echo "[OK] Сокет containerd доступен"
else
    echo "[FAIL] Сокет containerd отсутствует!"
fi

# 3. Kubelet
if systemctl is-enabled --quiet kubelet; then
    echo "[OK] kubelet включен в автозагрузку"
else
    echo "[FAIL] kubelet не настроен на автозагрузку!"
fi

# 4. Версии
kubeadm version -o short
kubelet --version
```

### Шаг 6: Верификация конфигурации containerd

Дополнительная проверка корректности настроек перед инициализацией кластера:

```bash
# Проверка SystemdCgroup
grep -A2 "SystemdCgroup" /etc/containerd/config.toml
# → SystemdCgroup = true

# Проверка pause-образа
grep "sandbox_image" /etc/containerd/config.toml
# → sandbox_image = "registry.k8s.io/pause:3.10"

# Проверка доступности crictl
sudo crictl info | jq '.config.containerd'
# → Должен вернуть конфигурацию containerd
```

### Шаг 7: Откат и очистка (при ошибках установки)

Если установка выполнена некорректно и необходим полный сброс:

```bash
# 1. Остановка сервисов
sudo systemctl stop kubelet
sudo systemctl stop containerd

# 2. Очистка конфигураций
sudo rm -rf /etc/containerd/config.toml
sudo rm -rf /etc/crictl.yaml

# 3. Удаление пакетов Kubernetes
# Ubuntu/Debian:
sudo apt purge -y kubelet kubeadm kubectl
sudo apt autoremove -y
sudo apt-mark unhold kubelet kubeadm kubectl

# RHEL/CentOS:
# sudo dnf remove -y kubelet kubeadm kubectl

# 4. Удаление containerd
# Ubuntu/Debian:
sudo apt purge -y containerd.io
sudo rm -rf /etc/containerd /var/lib/containerd

# RHEL/CentOS:
# sudo dnf remove -y containerd.io

# 5. Перезагрузка
sudo reboot
```

---

## Дополнительная информация

### Тюнинг для высоконагруженных сред

- **Registry Mirrors**: Если у вас есть локальный реестр (например, Harbor), настройте его в `/etc/containerd/config.toml` в секции `[plugins."io.containerd.grpc.v1.cri".registry.mirrors]`.
- **Garbage Collection**: Настройте пороги удаления образов (`image_gc_high_threshold`, `image_gc_low_threshold`) в конфигурации `kubelet` (`/var/lib/kubelet/config.yaml`), если диски имеют малый объем.
- **Лимиты ресурсов**: Для узлов с большим количеством подов увеличьте `LimitNOFILE` в systemd-юните containerd.

### Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Version Mismatch** | Установка `kubelet` v1.35 с `kubeadm` v1.34 | Всегда используйте пакеты одной минорной версии |
| **GPG Key Errors** | Использование старого ключа с `apt-key add` (устарело) | Всегда используйте `/etc/apt/keyrings/` |
| **SystemdCgroup=false** | containerd не настроен на systemd | `sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml` |
| **[ERROR CRI]: container runtime is not running** | containerd не запущен или сокет недоступен | `systemctl status containerd`; `ls -la /run/containerd/containerd.sock` |
| **kubelet не запускается** | Неверный cgroup driver или не отключён swap | `journalctl -u kubelet -f`; проверить `config.toml` containerd |
| **cgroup2fs не найден** | cgroup v2 не включен | Добавить `systemd.unified_cgroup_hierarchy=1` в GRUB, перезагрузиться |

### Безопасность

1. **GPG-ключи:** Всегда импортируйте GPG-ключи в `/etc/apt/keyrings/` (не используйте устаревший `apt-key add`).
2. **Репозитории:** Используйте только официальные репозитории (`pkgs.k8s.io`, `download.docker.com`).
3. **Минимальные привилегии:** Не запускайте `kubeadm` от имени `root` без необходимости. Используйте `sudo` для каждой команды.
4. **SELinux:** На RHEL/CentOS переведите в `Permissive` перед установкой; после стабилизации верните в `Enforcing` с правильными контекстами.

### Best Practices для production

1. **Начинайте с чистой ОС:** Избегайте клонирования VM с одинаковым `machine-id` — это приводит к конфликтам.
2. **Версионная согласованность:** `kubeadm`, `kubelet`, `kubectl` должны быть одной минорной версии на всех узлах.
3. **Фиксируйте версии:** Используйте `apt-mark hold` / `dnf versionlock` для предотвращения случайных обновлений.
4. **Раздельная сеть:** Control Plane и Worker узлы должны быть в одной L2/L3 сети (или иметь маршрутизацию).
5. **SSD для etcd:** Если etcd вынесен на отдельный диск, используйте SSD — etcd чувствителен к задержкам чтения/записи.
6. **Синхронизация времени:** Обязательно для HA — настройте Chrony до развёртывания kubeadm.
7. **Документируйте:** Храните конфигурации containerd и kubeadm в системе контроля версий.

### Интеграция с документацией

Установка компонентов — **шаг 3** в цикле развертывания.
1. [Требования к среде](./k8s_ha_environment_requirements.md)
2. [Подготовка ОС](./k8s_ha_node_preparation.md)
3. **Установка компонентов** (текущий файл)
4. [Инициализация Control Plane](../kubeadm/cluster_initialization.md)
5. [Установка CNI](./cni_installation.md)
6. [Присоединение узлов](./node_joining.md)

### См. также

- **[Руководство по подготовке узлов (kubeadm)](../kubeadm/kubeadm_installation_guide.md)** — полное руководство по установке с детальными пояснениями каждого шага.
- **[Container Runtime в Kubernetes](../../../Concepts/container_runtime.md)** — теория о рантаймах, CRI, сравнение containerd и CRI-O.
- **[Kubelet — агент Kubernetes](../../../Concepts/kubelet.md)** — архитектура, конфигурация, диагностика.
- **[Установка kubectl](../kubectl_installation.md)** — детальное руководство по установке kubectl на различных платформах.
