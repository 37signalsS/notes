# Установка компонентов Kubernetes на узлы

## Определения

**containerd** — индустриальный стандарт среды выполнения контейнеров (Container Runtime), реализующий спецификацию CRI. В современных кластерах (K8s 1.24+) является основным движком, обеспечивающим высокую производительность за счет отсутствия лишних прослоек (Docker-shim).

**CRI (Container Network Interface)** — интерфейс, позволяющий `kubelet` взаимодействовать с различными средами выполнения контейнеров.

**kubeadm** — утилита для автоматизации жизненного цикла кластера (инициализация, обновление, управление токенами и сертификатами).

**kubelet** — основной агент узла, отвечающий за выполнение контейнеров и проверку их состояния (Health Checks).

**kubectl** — инструмент командной строки для взаимодействия с API-сервером Kubernetes.

**pause image (Sandbox Image)** — служебный контейнер, который «держит» сетевое пространство имен (Network Namespace) и IPC для пода. Все остальные контейнеры пода подключаются к его ресурсам.

---

## Основные концепции

### Роль Container Runtime в архитектуре узла

`containerd` — это «рабочая лошадка» кластера. Он отвечает за:
- Скачивание и хранение образов.
- Создание и запуск контейнеров через `runc`.
- Управление снимками файловой системы (Snapshots).
- Организацию сетевых интерфейсов через CNI.

### Иерархия компонентов и их связи

1.  **kubelet** получает инструкции от API-сервера.
2.  **kubelet** вызывает **containerd** через gRPC сокет (`/run/containerd/containerd.sock`).
3.  **containerd** запускает контейнеры.
4.  **kubeadm** настраивает конфигурацию для первых двух компонентов.

---

## Практические сценарии

### Шаг 1: Установка и базовая настройка containerd

Рекомендуется использовать официальный репозиторий Docker для получения актуальных версий `containerd` с поддержкой последних функций безопасности.

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

---

## Дополнительная информация

### Тюнинг для высоконагруженных сред

- **Registry Mirrors**: Если у вас есть локальный реестр (например, Harbor), настройте его в `/etc/containerd/config.toml` в секции `[plugins."io.containerd.grpc.v1.cri".registry.mirrors]`.
- **Garbage Collection**: Настройте пороги удаления образов (`image_gc_high_threshold`, `image_gc_low_threshold`) в конфигурации `kubelet` (`/var/lib/kubelet/config.yaml`), если диски имеют малый объем.

### Типовые ошибки

*   **Version Mismatch**: Установка `kubelet` v1.35 с `kubeadm` v1.34. Всегда используйте пакеты одной минорной версии.
*   **GPG Key Errors**: Использование старого ключа с `apt-key add` (устарело). Всегда используйте `/etc/apt/keyrings/`.

### Интеграция с документацией

Установка компонентов — **шаг 3** в цикле развертывания.
1. [Требования к среде](./k8s_ha_environment_requirements.md)
2. [Подготовка ОС](./k8s_ha_node_preparation.md)
3. **Установка компонентов** (текущий файл)
4. [Инициализация Control Plane](../kubeadm/cluster_initialization.md)
5. [Установка CNI](./cni_installation.md)
6. [Присоединение узлов](./node_joining.md)

Подробнее о `containerd` см. в **[Альтернативные среды выполнения](../../../Docker/alternative_runtimes_and_tools.md)**.
