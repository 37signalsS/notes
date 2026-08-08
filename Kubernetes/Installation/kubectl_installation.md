# Установка kubectl

## Определения

**kubectl** — утилита командной строки (CLI) для взаимодействия с API-сервером Kubernetes. Позволяет развертывать приложения, просматривать ресурсы и управлять кластером.

## Базовые концепции

### Совместимость версий
Согласно политике Kubernetes, версия `kubectl` должна отличаться от версии API-сервера не более чем на одну минорную версию (в обе стороны). Например, клиент версии `v1.36` гарантированно работает с серверами `v1.35`, `v1.36` и `v1.37`.

Использование актуальной версии рекомендуется для доступа к новым функциям и исправлениям безопасности.

### Управление версиями и плагинами
Для управления несколькими версиями `kubectl` в рамках разных проектов рекомендуется использовать инструменты вроде **mise** или **asdf**. Для расширения возможностей CLI используется менеджер плагинов **krew**.

## Практические сценарии

### Установка на Linux

#### Прямая загрузка бинарного файла (рекомендуется для CI/CD)

```bash
# Загрузка актуальной стабильной версии
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
# → % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current

# Проверка контрольной суммы
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256"
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check
# → kubectl: OK

# Установка
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Проверка
kubectl version --client
# → Client Version: v1.36.2
```

#### Использование пакетных менеджеров (рекомендуется для рабочих станций)

**Для Ubuntu/Debian:**
```bash
sudo apt-get update && sudo apt-get install -y apt-transport-https ca-certificates curl gpg
sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.36/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.36/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update
sudo apt-get install -y kubectl
```

**Для RHEL/CentOS/Rocky Linux:**
```bash
cat <<EOF | sudo tee /etc/yum.repos.d/kubernetes.repo
[kubernetes]
name=Kubernetes
baseurl=https://pkgs.k8s.io/core:/stable:/v1.36/rpm/
enabled=1
gpgcheck=1
gpgkey=https://pkgs.k8s.io/core:/stable:/v1.36/rpm/repodata/repomd.xml.key
EOF

sudo dnf install -y kubectl
```

**Через Snap:**
```bash
sudo snap install kubectl --classic
# → kubectl v1.36.2 from Canonical✓ installed
```

### Установка на macOS

#### С использованием Homebrew
```bash
brew install kubectl
# → ==> Pouring kubectl--1.36.2.arm64_sonoma.bottle.tar.gz
# → 🍺  /opt/homebrew/Cellar/kubectl/1.36.2: 7 files, 53.4MB

kubectl version --client
```

#### Прямая загрузка (Apple Silicon)
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/darwin/arm64/kubectl"
chmod +x ./kubectl
sudo mv ./kubectl /usr/local/bin/kubectl
```

### Установка на Windows

#### С использованием Winget (рекомендуется)
```powershell
winget install -e --id Kubernetes.kubectl
```

#### С использованием PowerShell (бинарный файл)
```powershell
curl.exe -LO "https://dl.k8s.io/release/v1.36.2/bin/windows/amd64/kubectl.exe"
# → 100 52.1M  100 52.1M    0     0  20.1M      0  0:00:02
```

### Установка и настройка Krew (Plugin Manager)

Krew позволяет устанавливать плагины (например, `ctx`, `ns`, `sniff`).

```bash
# Установка (для Linux/macOS)
(
  set -x; cd "$(mktemp -d)" &&
  OS="$(uname | tr '[:upper:]' '[:lower:]')" &&
  ARCH="$(uname -m | sed -e 's/x86_64/amd64/' -e 's/\(arm\)\(64\)\?.*/\1\2/' -e 's/aarch64/arm64/')" &&
  KREW="krew-${OS}_${ARCH}" &&
  curl -fsSLO "https://github.com/kubernetes-sigs/krew/releases/latest/download/${KREW}.tar.gz" &&
  tar zxvf "${KREW}.tar.gz" &&
  ./"${KREW}" install krew
)

# Добавление в PATH (Zsh/Bash)
export PATH="${KREW_ROOT:-$HOME/.krew}/bin:$PATH"
```

### Настройка автодополнения и алиасов

#### Автодополнение (Autocomplete)
```bash
# Bash
source <(kubectl completion bash)
echo "source <(kubectl completion bash)" >> ~/.bashrc

# Zsh
source <(kubectl completion zsh)
echo "source <(kubectl completion zsh)" >> ~/.zshrc
```

#### Использование алиасов
Самый популярный алиас — `k`.
```bash
alias k=kubectl
complete -F __start_kubectl k # Для работы автодополнения с алиасом
```

## Дополнительная информация

**Полезные ссылки:**
* [Официальная документация Kubernetes](https://kubernetes.io/docs/tasks/tools/)
* **[Kubeconfig: Настройка подключения](../Operations/kubeconfig_and_connection.md)** — следующий шаг после установки.
* **[mise: Управление версиями](../../mise.md)** — декларативное управление версиями kubectl.
* [Kubectl Cheat Sheet](https://kubernetes.io/docs/reference/kubectl/cheatsheet/)
