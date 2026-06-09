# RKE: Установка kubectl и настройка доступа

## Определения

**kubectl** — CLI-утилита командной строки для управления кластером Kubernetes через API.

**kubeconfig** — YAML-файл конфигурации доступа к Kubernetes API. Содержит контексты, пользователей, кластеры и сертификаты.

**контекст** — набор параметров доступа к кластеру (кластер + пользователь + namespace по умолчанию).

## Базовые концепции

### Требования к версии kubectl

Версия kubectl должна совпадать с версией кластера (допускается отклонение ±1 минорную версию).

Проверка версии кластера:

```bash
kubectl version --short
```

## Практические сценарии

### Установка kubectl

**Linux (AMD64):**

```bash
# Скачивание актуальной версии
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"

# Проверка контрольной суммы (опционально)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256"
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check

# Установка
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# Проверка
kubectl version --client
```

**macOS (Homebrew):**

```bash
brew install kubectl
kubectl version --client
```

**Windows (PowerShell):**

```powershell
curl.exe -LO "https://dl.k8s.io/release/v1.31.0/bin/windows/amd64/kubectl.exe"
```

### Получение kubeconfig из Rancher UI

1. **Открыть Rancher UI** (`https://rancher.your-domain.com`)

2. **Выбрать кластер:**
   - Перейти в `Cluster Management` или `Dashboard`
   - Кликнуть на нужный RKE-кластер

3. **Получить kubeconfig:**
   - Нажать кнопку `Kubeconfig File` (верхний правый угол)
   - Или `Explore` → `⋮` → `Download KubeConfig`

4. **Сохранить локально:**

   ```bash
   mkdir -p $HOME/.kube
   nano $HOME/.kube/config  # Вставить содержимое из буфера
   chmod 600 $HOME/.kube/config
   ```

5. **Проверить доступ:**

   ```bash
   kubectl get nodes
   kubectl get pods --all-namespaces
   ```

### Работа с несколькими контекстами

**Просмотр контекстов:**

```bash
kubectl config get-contexts
```

**Переключение контекста:**

```bash
kubectl config use-context c-m-xxxxxxxxx  # Имя из Rancher
```

**Слияние конфигураций:**

Если уже есть `~/.kube/config` (например, от kubeadm):

```bash
# Резервное копирование
cp ~/.kube/config ~/.kube/config.backup

# Установка переменной для нового файла
export KUBECONFIG=~/.kube/config:~/.kube/rke-config

# Проверка доступных контекстов
kubectl config get-contexts

# Переключение на RKE контекст
kubectl config use-context c-m-xxxxxxxxx
```

**Текущий контекст:**

```bash
kubectl config current-context
```

### Настройка автодополнения (autocomplete)

**Bash:**

```bash
source <(kubectl completion bash)
echo "source <(kubectl completion bash)" >> ~/.bashrc
```

**Zsh:**

```bash
source <(kubectl completion zsh)
echo "source <(kubectl completion zsh)" >> ~/.zshrc
```

**Fish:**

```bash
kubectl completion fish | source
echo "kubectl completion fish | source" >> ~/.config/fish/config.fish
```

## Дополнительная информация

**Безопасность kubeconfig:**

- Установить права: `chmod 600 ~/.kube/config`
- Не передавать файл через незащищенные каналы
- Использовать ServiceAccount с минимальными правами для CI/CD

**См. также:** [RKE: Основные концепции](./rke_concepts.md), [RKE: Управление и поиск неисправностей](./rke_management_scenarios.md), [kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md).
