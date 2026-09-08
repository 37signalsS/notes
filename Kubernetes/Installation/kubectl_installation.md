# Установка kubectl

## Определения

**kubectl** — утилита командной строки (CLI) для взаимодействия с API-сервером Kubernetes. Позволяет развертывать приложения, просматривать ресурсы и управлять кластером.

**Основные функции kubectl:**
- Создание, изменение и удаление ресурсов Kubernetes (Pods, Deployments, Services, ConfigMaps и др.)
- Просмотр состояния кластера и ресурсов
- Выполнение команд внутри контейнеров (`kubectl exec`)
- Перенаправление портов (`kubectl port-forward`)
- Копирование файлов между локальной машиной и подами (`kubectl cp`)
- Управление конфигурацией через `kubectl apply`, `kubectl delete`, `kubectl patch`

## Базовые концепции

### Совместимость версий
Согласно политике Kubernetes, версия `kubectl` должна отличаться от версии API-сервера не более чем на одну минорную версию (в обе стороны). Например, клиент версии `v1.36` гарантированно работает с серверами `v1.35`, `v1.36` и `v1.37`.

Использование актуальной версии рекомендуется для доступа к новым функциям и исправлениям безопасности.

**Проверка версий:**
```bash
# Версия клиента (установленного kubectl)
kubectl version --client
# → Client Version: v1.36.2

# Версия сервера (если доступен API-сервер)
kubectl version --short
# → Client Version: v1.36.2
# → Server Version: v1.36.1
```

**При несоответствии версий** kubectl может работать некорректно:部分ные команды выполняются, но возникают ошибки при работе с новыми API-ресурсами или полями. В продакшен-средах рекомендуется поддерживать одинаковую минорную версию клиента и сервера.

### Управление версиями и плагинами
Для управления несколькими версиями `kubectl` в рамках разных проектов рекомендуется использовать инструменты вроде **mise** или **asdf**. Для расширения возможностей CLI используется менеджер плагинов **krew**.

**Управление версиями через mise:**
```toml
# .mise.toml в корне проекта
[tools]
kubectl = "1.36.2"
```

При переходе в директорию проекта `mise` автоматически активирует указанную версию `kubectl`.

### Переменные окружения kubectl

kubectl поддерживает несколько переменных окружения для настройки поведения:

| Переменная | Описание | Пример |
|:---|:---|:---|
| `KUBECONFIG` | Путь(и) к файлам конфигурации | `~/.kube/config:~/.kube/prod.yaml` |
| `KUBERNETES_SERVICE_HOST` | IP-адрес API-сервера (используется в кластере) | `10.96.0.1` |
| `KUBERNETES_SERVICE_PORT` | Порт API-сервера (по умолчанию 6443) | `6443` |
| `KUBECONFIG` | Приоритет: флаг `--kubeconfig` > переменная `KUBECONFIG` | — |

**Пример использования:**
```bash
# Использование нескольких конфигов
export KUBECONFIG=~/.kube/config:~/.kube/staging.yaml:~/.kube/prod.yaml

# Отключение проверки TLS (только для тестирования)
export KUBEINSECURE_SKIP_TLS_VERIFY=true
```

### Структура директорий kubectl

По умолчанию kubectl использует следующие пути:

| Путь | Назначение |
|:---|:---|
| `~/.kube/config` | Основной конфигурационный файл |
| `~/.kube/cache/` | Кэш ответов API-сервера |
| `~/.kube/plugins/` | Директория для плагинов Krew |

**Важно:** файл `~/.kube/config` содержит секреты (токены, сертификаты). Проверьте права доступа:
```bash
chmod 600 ~/.kube/config
ls -la ~/.kube/config
# → -rw------- 1 user user 2847 Sep 2 10:00 /Users/user/.kube/config
```

## Практические сценарии

### Предварительные требования

- **Сетевой доступ:** возможность загружать пакеты из `dl.k8s.io` и `pkgs.k8s.io`
- **Права root:** для установки в системные директории (`/usr/local/bin`)
- **Проверка SHA256:** для верификации целостности бинарного файла (рекомендуется для продакшена)

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

**Пинning версии (для воспроизводимости):**
```bash
# Установка конкретной версии вместо стабильной
KUBECTL_VERSION="v1.36.2"
curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256"
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
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

**Проверка после установки:**
```bash
which kubectl
# → /usr/local/bin/kubectl

kubectl version --client --short
# → Client Version: v1.36.2
```

### Установка на macOS

#### С использованием Homebrew
```bash
brew install kubectl
# → ==> Pouring kubectl--1.36.2.arm64_sonoma.bottle.tar.gz
# → 🍺  /opt/homebrew/Cellar/kubectl/1.36.2: 7 files, 53.4MB

kubectl version --client
```

**Управление версиями через Homebrew:**
```bash
# Просмотр доступных версий
brew search kubectl

# Установка предыдущей версии
brew install kubernetes-cli@1.35

# Переключение между версиями
brew unlink kubernetes-cli@1.36
brew link --force kubernetes-cli@1.35
```

#### Прямая загрузка (Apple Silicon)
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/darwin/arm64/kubectl"
chmod +x ./kubectl
sudo mv ./kubectl /usr/local/bin/kubectl

# Проверка
kubectl version --client
```

#### Прямая загрузка (Intel Mac)
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/darwin/amd64/kubectl"
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

# Перемещение в PATH (например, в C:\kubectl)
Move-Item .\kubectl.exe C:\kubectl\kubectl.exe

# Добавление в PATH (временно)
$env:PATH += ";C:\kubectl"

# Добавление в PATH (постоянно)
[Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";C:\kubectl", "User")
```

#### С использованием Chocolatey
```powershell
choco install kubernetes-cli
```

### Установка в CI/CD (GitHub Actions)

```yaml
# .github/workflows/k8s-deploy.yml
steps:
  - name: Install kubectl
    uses: azure/setup-kubectl@v3
    with:
      version: 'v1.36.2'

  # Или черезmise
  - name: Setup mise
    uses: jdx/mise-action@v2
    with:
      tools: kubectl@1.36.2
```

### Установка и настройка Krew (Plugin Manager)

Krew позволяет устанавливать плагины (например, `ctx`, `ns`, `sniff`). Это аналог `apt` или `brew` для kubectl.

#### Установка Krew

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
```

**Настройка PATH для Krew:**
```bash
# Добавление в PATH (Zsh/Bash)
export PATH="${KREW_ROOT:-$HOME/.krew}/bin:$PATH"

# Для постоянного использования добавьте в ~/.bashrc или ~/.zshrc
echo 'export PATH="${KREW_ROOT:-$HOME/.krew}/bin:$PATH"' >> ~/.zshrc
```

**Проверка установки:**
```bash
kubectl krew --version
# → v0.4.7
```

#### Управление плагинами

```bash
# Просмотр доступных плагинов
kubectl krew search

# Установка плагина
kubectl krew install ctx
kubectl krew install ns
kubectl krew install sniff
kubectl krew install tree

# Просмотр установленных плагинов
kubectl krew list

# Обновление всех плагинов
kubectl krew update

# Удаление плагина
kubectl krew uninstall ctx
```

#### Популярные плагины для DevOps/SRE

| Плагин | Назначение | Пример использования |
|:---|:---|:---|
| **ctx** | Быстрое переключение контекстов | `kubectl ctx prod-cluster` |
| **ns** | Быстрое переключение namespaces | `kubectl ns monitoring` |
| **tree** | Визуализация иерархии ресурсов | `kubectl tree deploy my-app` |
| **sniff** | Перехват трафика пода (аналог tcpdump) | `kubectl sniff <pod-name>` |
| **whoami** | Информация о текущем пользователе | `kubectl whoami` |
| **neat** | Очистка YAML от служебных полей | `kubectl get deploy my-app -o yaml \| kubectl neat` |
| **resources** | Просмотр ресурсов пода | `kubectl resources pod <pod-name>` |
| **popeye** | Автоматический аудит кластера | `kubectl popeye --all-namespaces` |

### Настройка автодополнения и алиасов

#### Автодополнение (Autocomplete)

Автодополнение значительно ускоряет работу с kubectl, позволяя нажатием Tab получать имена ресурсов, подов, сервисов и т.д.

**Для Bash:**
```bash
# Включение автодополнения
source <(kubectl completion bash)

# Для постоянного использования
echo "source <(kubectl completion bash)" >> ~/.bashrc

# Автодополнение для алиаса 'k'
echo 'complete -F __start_kubectl k' >> ~/.bashrc
```

**Для Zsh:**
```bash
# Включение автодополнения
source <(kubectl completion zsh)

# Для постоянного использования
echo "source <(kubectl completion zsh)" >> ~/.zshrc

# Автодополнение для алиаса 'k'
echo 'complete -F __start_kubectl k' >> ~/.zshrc

# Или через композицию (если используете oh-my-zsh)
# Добавьте в ~/.zshrc:
# plugins=(kubectl)
```

**Для Fish:**
```fish
# Генерация автодополнения
kubectl completion fish | source

# Для постоянного использования
kubectl completion fish > ~/.config/fish/completions/kubectl.fish
```

#### Использование алиасов

Самый популярный алиас — `k`. Это сокращение экономит время при частом использовании kubectl.

```bash
# Базовый алиас
alias k=kubectl
alias kg='kubectl get'
alias kd='kubectl describe'
alias kl='kubectl logs'
alias ke='kubectl exec'
alias ka='kubectl apply -f'

# Автодополнение для алиаса
complete -F __start_kubectl k
complete -F __start_kubectl kg
complete -F __start_kubectl kd
```

**Эффективные алиасы для DevOps:**
```bash
# Быстрый просмотр подов в пространстве имен
alias kgp='kubectl get pods -o wide'
alias kgpall='kubectl get pods --all-namespaces -o wide'

# Быстрый просмотр сервисов
alias kgs='kubectl get svc'
alias kgsw='kubectl get svc -o wide'

# Быстрый просмотр нод
alias kgn='kubectl get nodes -o wide'

# Логи с непрерывным выводом
alias klfc='kubectl logs -f --tail=100'

# Экспорт манифеста
alias kgy='kubectl get deploy -o yaml'
```

#### Дополнительные инструменты

**kubectx и kubens (быстрое переключение):**
```bash
# Установка через Homebrew
brew install kubectx

# Переключение контекста
kubectx prod-cluster
kubectx -  # Вернуться к предыдущему

# Переключение namespace
kubens monitoring
kubens -  # Вернуться к предыдущему
```

**k9s (терминальный UI):**
```bash
# Установка
brew install k9s

# Запуск
k9s

# Навигация:
# :ctx - переключение контекста
# :ns - переключение namespace
# Ctrl+d - удаление пода
# :q - выход
```

## Диагностика и устранение проблем

### Типичные ошибки при установке

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **`kubectl: command not found`** | kubectl не установлен или не добавлен в PATH | Проверьте `which kubectl`. Если не найден, установите kubectl или добавьте директорию с бинарным файлом в PATH |
| **`permission denied`** | Недостаточные права на выполнение файла | `chmod +x kubectl` или `sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl` |
| **`curl: (60) SSL certificate problem`** | Проблемы с SSL-сертификатом при загрузке | Используйте `curl -k` (небезопасно) или обновите CA-сертификаты: `sudo apt-get update && sudo apt-get install -y ca-certificates` |
| **`The connection to the server was refused`** | API-сервер недоступен или неверный IP/port | Проверьте `kubectl config view --minify`. Убедитесь, что API-сервер доступен по сети |
| **`Unable to connect to the server: x509: certificate has expired`** | Истек клиентский сертификат | Обновите сертификаты или получите новый kubeconfig |
| **`error: the server doesn't have a resource type "nodes"`** | Несоответствие версий клиента и сервера | Проверьте `kubectl version`. Обновите kubectl или получите новый kubeconfig |
| **`Unable to read CA certificate`** | Поврежден или отсутствует CA-сертификат | Проверьте `~/.kube/config` или обновите CA-данные |

### Проверка работоспособности kubectl

```bash
# 1. Проверка установки
which kubectl
# → /usr/local/bin/kubectl

# 2. Проверка версии клиента
kubectl version --client
# → Client Version: v1.36.2

# 3. Проверка подключения к кластеру
kubectl cluster-info
# → Kubernetes control plane is running at https://192.168.1.100:6443

# 4. Просмотр текущего контекста
kubectl config current-context
# → prod-admin

# 5. Просмотр всех контекстов
kubectl config get-contexts

# 6. Проверка подключения к API-серверу
kubectl get nodes
# → NAME STATUS ROLES AGE VERSION
# → master Ready control-plane 30d v1.36.1
```

### Устранение проблем с версиями

**Проблема: кластер старше, чем kubectl:**
```bash
# Проверка версии сервера
kubectl version --short
# → Client Version: v1.36.2
# → Server Version: v1.35.4

# Решение: установите версию kubectl, совместимую с сервером
curl -LO "https://dl.k8s.io/release/v1.35.4/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

**Проблема: несколько версий kubectl в системе:**
```bash
# Найти все версии kubectl
find /usr -name "kubectl" -type f 2>/dev/null
# → /usr/local/bin/kubectl
# → /usr/bin/kubectl

# Определить, какая используется
which -a kubectl
# → /usr/local/bin/kubectl
# → /usr/bin/kubectl

# Удалить дубликат (если не нужен)
sudo rm /usr/bin/kubectl
```

### Устранение проблем с Krew

```bash
# Проверка корректности установки Krew
kubectl krew version
# → v0.4.7

# Если Krew не работает, проверьте PATH
echo $PATH | grep -q "\.krew" && echo "Krew в PATH" || echo "Krew не в PATH"

# Переустановка Krew
(
  set -x; cd "$(mktemp -d)" &&
  OS="$(uname | tr '[:upper:]' '[:lower:]')" &&
  ARCH="$(uname -m | sed -e 's/x86_64/amd64/' -e 's/\(arm\)\(64\)\?.*/\1\2/' -e 's/aarch64/arm64/')" &&
  KREW="krew-${OS}_${ARCH}" &&
  curl -fsSLO "https://github.com/kubernetes-sigs/krew/releases/latest/download/${KREW}.tar.gz" &&
  tar zxvf "${KREW}.tar.gz" &&
  ./"${KREW}" install krew
)
```

### Устранение проблем с автодополнением

```bash
# Проверка, что автодополнение загружено
type complete
# → complete is a shell builtin

# Если автодополнение не работает, загрузите его вручную
source <(kubectl completion bash)

# Для Zsh с oh-my-zsh
# Убедитесь, что в ~/.zshrc есть:
# plugins=(kubectl)
#source <(kubectl completion zsh)
```

## Дополнительная информация

### Лучшие практики

- **Безопасность:** Никогда не храните kubeconfig с правами администратора (admin.conf) в открытом доступе. Генерируйте отдельные kubeconfig с ограниченными правами через RBAC.
- **Версионирование:** Используйте `mise` или `.tool-versions` для декларативного управления версией kubectl в проектах.
- **CI/CD:** В пайплайнах фиксируйте версию kubectl для воспроизводимости (например, `kubectl@1.36.2`).
- **Автодополнение:** Включите автодополнение и алиасы для повышения продуктивности.
- **Плагины:** Используйте Krew для расширения возможностей kubectl (tree, popeye, sniff).

### Связанные темы

**После установки kubectl:**
1. **[Kubeconfig: Настройка подключения](../Operations/kubeconfig_and_connection.md)** — настройка доступа к кластеру (следующий шаг).
2. **[RBAC: Контроль доступа](../Security/rbac/rbac_overview.md)** — настройка прав для пользователей и ServiceAccount.
3. **[Troubleshooting: API Access Forbidden](../Troubleshooting/Common_Errors/ApiAccessForbidden/common.md)** — решение проблем с авторизацией.

**Смежные инструменты:**
- **[mise: Управление версиями](../../mise.md)** — декларативное управление версиями kubectl и других инструментов.
- **[Helm: Пакетный менеджер](../ToolsUtilities/Helm/)** — управление приложениями через шаблоны.
- **[k9s: Терминальный UI](https://k9scli.io/)** — интерактивный интерфейс для kubectl.

### Полезные команды

```bash
# Быстрый обзор кластера
kubectl get nodes
kubectl get pods --all-namespaces

# Информация о ресурсе
kubectl explain pod
kubectl explain deployment

# Логи пода
kubectl logs <pod-name> --previous  # Логи предыдущего контейнера

# Копирование файлов
kubectl cp <pod-name>:/path/to/file ./local-file

# Перенаправление портов
kubectl port-forward svc/my-service 8080:80

# Выполнение команды в поде
kubectl exec -it <pod-name> -- /bin/sh
```
