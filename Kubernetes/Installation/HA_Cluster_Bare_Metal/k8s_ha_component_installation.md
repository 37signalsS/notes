### 3. Установка компонентов (на всех узлах)

#### Установка и настройка среды выполнения `containerd`

**Цель:** Установить `containerd` и настроить его как CRI (Container Runtime Interface) для Kubernetes, обеспечив корректную работу с `systemd` и сохранив совместимость с существующими Docker-контейнерами, если они есть.

**Шаг 3.1: Установка `containerd`**

```bash
# Обновляем список пакетов и устанавливаем containerd
sudo apt-get update
sudo apt-get install -y containerd

# Проверяем успешность установки
containerd --version
```

**Шаг 3.2: Конфигурация `containerd` для Kubernetes**

```bash
# Создаём директорию для конфигурации, если её нет
sudo mkdir -p /etc/containerd

# Генерируем конфигурацию по умолчанию.
# Перед этим создаем бэкап, если файл уже существует.
if [ -f /etc/containerd/config.toml ]; then
    sudo cp /etc/containerd/config.toml /etc/containerd/config.toml.backup.$(date +%Y%m%d_%H%M)
fi
sudo containerd config default | sudo tee /etc/containerd/config.toml

# Включаем драйвер Systemd Cgroup для корректной интеграции с kubelet.
# Это критически важный шаг для управления ресурсами подов.
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml

# Устанавливаем официальный pause-образ от Kubernetes.
# Он используется для создания сетевого пространства имен для каждого пода.
sudo sed -i 's|sandbox_image = ".*"|sandbox_image = "registry.k8s.io/pause:3.9"|' /etc/containerd/config.toml

# Проверяем, что ключевые изменения применились
echo "Проверка настроек containerd:"
sudo grep -E "SystemdCgroup|sandbox_image" /etc/containerd/config.toml
```

**Шаг 3.3: Перезапуск сервиса и проверка**

```bash
# Перезапускаем containerd для применения новой конфигурации
sudo systemctl restart containerd
sudo systemctl enable containerd

# Проверяем, что сервис активен и CRI-сокет доступен
sudo systemctl status containerd | grep "Active"
ls -la /run/containerd/containerd.sock
test -S /run/containerd/containerd.sock && echo "CRI socket: OK" || echo "CRI socket: MISSING"

# Проверка доступности API containerd через утилиту 'ctr'
ctr version >/dev/null 2>&1 && echo "Containerd API: OK" || echo "Containerd API: FAILED"

# Проверка применённых настроек, особенно параметра SystemdCgroup
containerd config dump | grep -A1 "SystemdCgroup"

# Предварительная проверка pause-образа (опционально):
# Kubelet автоматически загрузит его при необходимости.
ctr --namespace k8s.io images pull registry.k8s.io/pause:3.9 2>&1 | grep -q "success" && echo "Pause image: OK" || echo "Pause image: WILL BE PULLED BY KUBELET"
```

По завершении этого шага `containerd` будет корректно сконфигурирован для Kubernetes, CRI-сокет будет доступен, и система будет готова к установке компонентов Kubernetes. Все необходимые системные настройки будут применены.

**Следующий этап:** Установка `kubeadm`, `kubelet`, `kubectl` версии 1.34. Перезагрузка всех нод будет выполнена после полной установки компонентов Kubernetes.

#### Установка `kubeadm`, `kubelet`, `kubectl`

**Добавление репозитория Kubernetes (v1.34)**

```bash
# Обновляем список пакетов и устанавливаем зависимости
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl gpg

# Добавляем GPG-ключ для Kubernetes v1.34
# Новый URL для ключей pkgs.k8s.io
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.34/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# Добавляем репозиторий Kubernetes v1.34
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.34/deb/ /" | sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update
```

**Установка и настройка компонентов**

```bash
# Устанавливаем компоненты версии 1.34
sudo apt-get install -y kubelet=1.34.* kubeadm=1.34.* kubectl=1.34.*

# Фиксируем версии, чтобы избежать случайных обновлений
sudo apt-mark hold kubelet kubeadm kubectl

# Включаем службу kubelet в автозагрузку.
# Kubelet будет запущен автоматически после инициализации кластера с помощью kubeadm.
sudo systemctl enable kubelet
```

Все компоненты Kubernetes (`kubeadm`, `kubelet`, `kubectl`) версии 1.34 установлены, их версии зафиксированы, а `kubelet` включен в автозагрузку, ожидая инициализации кластера.

> **Важно:** На данном этапе НЕ ВЫПОЛНЯЙТЕ `kubeadm init`. Сначала необходимо убедиться, что все узлы находятся в одинаковом состоянии. После этого рекомендуется перезагрузить серверы для применения всех настроек, включая обновление ядра.