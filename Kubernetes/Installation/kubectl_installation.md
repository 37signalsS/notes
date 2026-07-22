# Установка kubectl

## Определения

**kubectl** — утилита командной строки (CLI) для взаимодействия с API-сервером Kubernetes. Позволяет развертывать приложения, просматривать ресурсы и управлять кластером.

## Базовые концепции

### Совместимость версий
Согласно политике Kubernetes, версия `kubectl` должна отличаться от версии API-сервера не более чем на одну минорную версию (в обе стороны). Например, клиент версии `v1.36` гарантированно работает с серверами `v1.35`, `v1.36` и `v1.37`.

Использование актуальной версии рекомендуется для доступа к новым функциям и исправлениям безопасности.

## Практические сценарии

### Установка на Linux

#### Прямая загрузка бинарного файла (рекомендуется)

```bash
# Загрузка актуальной стабильной версии
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
# → % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
# →                                 Dload  Upload   Total   Spent    Left  Speed
# → 100 52.1M  100 52.1M    0     0  25.4M      0  0:00:02  0:00:02 --:--:-- 25.4M

# Проверка контрольной суммы (опционально)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl.sha256"
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check
# → kubectl: OK

# Установка
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Проверка версии
kubectl version --client
# → Client Version: v1.36.2
# → Kustomize Version: v5.0.4-0.20230601165947-6ce0e23909fd
```

### Установка на macOS

#### С использованием Homebrew
```bash
brew install kubectl
# → ==> Downloading https://ghcr.io/v2/homebrew/core/kubectl/manifests/1.36.2
# → ==> Pouring kubectl--1.36.2.arm64_sonoma.bottle.tar.gz
# → 🍺  /opt/homebrew/Cellar/kubectl/1.36.2: 7 files, 53.4MB

kubectl version --client
# → Client Version: v1.36.2
```

### Установка на Windows

#### С использованием PowerShell
```powershell
curl.exe -LO "https://dl.k8s.io/release/v1.36.2/bin/windows/amd64/kubectl.exe"
# → % Total    % Received % Xferd  Average Speed   Time    Time     Time  Current
# →                                 Dload  Upload   Total   Spent    Left  Speed
# → 100 52.1M  100 52.1M    0     0  20.1M      0  0:00:02  0:00:02 --:--:-- 20.1M

# Добавление в PATH (опционально, если не в директории из PATH)
# Переместите kubectl.exe в удобную папку и добавьте её в переменные окружения.
```

### Настройка автодополнения (Autocomplete)

Для удобства работы рекомендуется включить автодополнение команд.

#### Bash
```bash
source <(kubectl completion bash)
echo "source <(kubectl completion bash)" >> ~/.bashrc
```

#### Zsh
```bash
source <(kubectl completion zsh)
echo "source <(kubectl completion zsh)" >> ~/.zshrc
```

#### Fish
```bash
kubectl completion fish | source
echo "kubectl completion fish | source" >> ~/.config/fish/config.fish
```

## Дополнительная информация

**Полезные ссылки:**
* [Официальная документация по установке](https://kubernetes.io/docs/tasks/tools/)
* [Настройка kubeconfig и подключение](../Operations/kubeconfig_and_connection.md)
* [Использование алиасов (k=kubectl)](https://kubernetes.io/docs/reference/kubectl/cheatsheet/#bash)
