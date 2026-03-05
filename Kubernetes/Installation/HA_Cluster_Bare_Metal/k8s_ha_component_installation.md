# Установка компонентов Kubernetes на узлы

## Определения

**containerd** — CRI-совместимая среда выполнения контейнеров для Kubernetes. Демон, управляющий жизненным циклом контейнеров. Подробнее: [Альтернативные среды выполнения](../../Docker/alternative_runtimes_and_tools.md).

**CRI (Container Runtime Interface)** — API Kubernetes для взаимодействия `kubelet` со средой выполнения контейнеров.

**kubeadm** — инструмент для инициализации и управления кластером Kubernetes.

**pause image** — базовый образ-инфраструктура, используемый Kubernetes для создания network namespace пода.

---

## Основные концепции

### Роль containerd в Kubernetes

`containerd` заменяет Docker в качестве среды выполнения для Kubernetes (начиная с версии 1.24, когда был удалён `dockershim`).

**Преимущества containerd**:

- Легковесный — только необходимый функционал для CRI
- Проект CNCF — независим от Docker
- Стабильный API — меньше breaking changes
- Нативная поддержка CRI — не требуется shim

### Компоненты Kubernetes

| Компонент | Назначение | Устанавливается на |
| :--- | :--- | :--- |
| **kubeadm** | Инициализация и управление кластером | Все узлы |
| **kubelet** | Агент узла, управление подами | Все узлы |
| **kubectl** | CLI для управления кластером | Все узлы (опционально на worker) |

---

## Практические сценарии

### Шаг 1: Установка containerd на все узлы

```bash
# Обновление списка пакетов
sudo apt-get update

# Установка containerd
sudo apt-get install -y containerd

# Проверка версии
containerd --version
```

### Шаг 2: Конфигурация containerd для Kubernetes

#### Создание конфигурации

```bash
# Создать директорию конфигурации
sudo mkdir -p /etc/containerd

# Создать бэкап существующей конфигурации
if [ -f /etc/containerd/config.toml ]; then
    sudo cp /etc/containerd/config.toml /etc/containerd/config.toml.backup.$(date +%Y%m%d_%H%M)
fi

# Сгенерировать конфигурацию по умолчанию
sudo containerd config default | sudo tee /etc/containerd/config.toml
```

#### Настройка для Kubernetes

```bash
# Включить SystemdCgroup для корректной интеграции с kubelet
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

# Установить официальный pause-образ от Kubernetes
# ВЕРСИЯ: Проверить актуальную версию pause образа
sudo sed -i 's|sandbox_image = ".*"|sandbox_image = "registry.k8s.io/pause:3.9"|' /etc/containerd/config.toml

# Проверка применённых настроек
echo "=== Проверка настроек containerd ==="
sudo grep -E "SystemdCgroup|sandbox_image" /etc/containerd/config.toml
```

**Почему SystemdCgroup = true**:

- Kubernetes использует systemd для управления ресурсами
- Без этой настройки `kubelet` не сможет корректно управлять подами
- Требуется для cgroups v2

### Шаг 3: Перезапуск и проверка containerd

```bash
# Перезапуск сервиса
sudo systemctl restart containerd
sudo systemctl enable containerd

# Проверка статуса
sudo systemctl status containerd | grep "Active"

# Проверка CRI-сокета
ls -la /run/containerd/containerd.sock
test -S /run/containerd/containerd.sock && echo "✅ CRI socket: OK" || echo "❌ CRI socket: MISSING"

# Проверка API containerd
ctr version >/dev/null 2>&1 && echo "✅ Containerd API: OK" || echo "❌ Containerd API: FAILED"

# Проверка настроек SystemdCgroup
containerd config dump | grep -A1 "SystemdCgroup"

# Предварительная загрузка pause-образа (опционально)
# Kubelet загрузит его автоматически при необходимости
ctr --namespace k8s.io images pull registry.k8s.io/pause:3.9
```

### Шаг 4: Установка kubeadm, kubelet, kubectl

#### Добавление репозитория Kubernetes

```bash
# Установка зависимостей
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl gpg

# Добавление GPG-ключа Kubernetes
# ВЕРСИЯ: 1.34 указана в оригинале — проверить актуальность
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.34/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# Добавление репозитория
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.34/deb/ /" | sudo tee /etc/apt/sources.list.d/kubernetes.list

# Обновление списка пакетов
sudo apt-get update
```

> **Важно**: Версия Kubernetes 1.34 указана в исходном файле. Проверьте актуальную стабильную версию в [официальной документации](https://kubernetes.io/releases/).

#### Установка компонентов

```bash
# Установка конкретной версии (замените 1.34.* на актуальную)
sudo apt-get install -y kubelet=1.34.* kubeadm=1.34.* kubectl=1.34.*

# Фиксация версий (предотвращение случайного обновления)
sudo apt-mark hold kubelet kubeadm kubectl

# Включение kubelet в автозагрузку
# Kubelet запустится после инициализации кластера через kubeadm
sudo systemctl enable kubelet

# Проверка версий
kubeadm version
kubelet --version
kubectl version --client
```

### Шаг 5: Итоговая проверка

```bash
echo "=== Проверка готовности компонентов ==="

# containerd
systemctl is-active containerd && echo "✅ containerd: активен" || echo "❌ containerd: не активен"

# CRI socket
test -S /run/containerd/containerd.sock && echo "✅ CRI socket: доступен" || echo "❌ CRI socket: отсутствует"

# Версии Kubernetes
echo "kubeadm: $(kubeadm version -o short)"
echo "kubelet: $(kubelet --version)"
echo "kubectl: $(kubectl version --client -o short)"

# Статус фиксации версий
apt-mark showhold | grep -E "kubelet|kubeadm|kubectl" && echo "✅ Версии зафиксированы" || echo "⚠️ Версии не зафиксированы"
```

---

## Дополнительная информация

### Что НЕ делается на этом этапе

- **kubeadm init** — не выполняется до готовности всех узлов
- **Перезагрузка** — выполняется после установки на все узлы
- **Настройка Control Plane** — следующий этап

### Версии компонентов (требует проверки)

| Компонент | Версия в файле | Статус | Примечание |
| :--- | :--- | :--- | :--- |
| **Kubernetes** | 1.34.* | ⚠️ Проверить | Уточнить актуальность |
| **containerd** | из репозитория ОС | ✅ | 1.6+ совместим с K8s 1.24-1.34 |
| **pause image** | 3.9 | ⚠️ Проверить | Актуальная версия может быть новее |
| **Calico** | v3.31.0 | ⚠️ Проверить | В файле k8s_ha_control_plane_and_cni.md |

### Связанные документы

- **Подготовка узлов**: [Node Preparation](./k8s_ha_node_preparation.md)
- **Control Plane**: [Control Plane & CNI](./k8s_ha_control_plane_and_cni.md)
- **containerd**: [Альтернативные среды выполнения](../../Docker/alternative_runtimes_and_tools.md)
- **kubeadm**: [Quickstart](../kudeadm/kubeadm_quickstart.md)
- **CNI**: [CNI Overview](../../Networking/Network/cni_overview.md)

### Надежность

| Раздел | Confidence |
| :--- | :--- |
| Установка containerd | Этот файл | 10 |
| Конфигурация SystemdCgroup | Этот файл | 10 |
| Версии Kubernetes | Требует проверки | 7 |
| Версии Calico | Требует проверки | 7 |
