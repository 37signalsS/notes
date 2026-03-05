# Использование kubeswitches

## Определения

**Использование kubeswitches** — практические сценарии установки, настройки и переключения между контекстами Kubernetes.

> **Навигация:** [Главная kubeswitches](./index.md) | [Операции](./operations.md)

---

## Practical Scenarios

### Установка

**macOS (Homebrew):**

```bash
# Если доступен в homebrew
brew install kubeswitches
```

**Ручная установка (Linux/macOS):**

```bash
# Загрузка бинарного файла (замените URL на актуальный)
curl -LO https://github.com/your-org/kubeswitches/releases/latest/download/kubeswitches-linux-amd64

# Установка
chmod +x kubeswitches-linux-amd64
sudo mv kubeswitches-linux-amd64 /usr/local/bin/kubeswitches
```

**Сборка из исходников:**

```bash
git clone https://github.com/your-org/kubeswitches.git
cd kubeswitches
go build -o kubeswitches ./cmd/kubeswitches
sudo mv kubeswitches /usr/local/bin/
```

---

### Первоначальная настройка

**Шаг 1: Создание директории для контекстов**

```bash
mkdir -p ~/.kube/contexts
```

**Шаг 2: Настройка переменной окружения**

```bash
echo 'export KUBESWITCH_CONTEXT_DIR="$HOME/.kube/contexts"' >> ~/.bashrc
source ~/.bashrc
```

**Шаг 3: Резервное копирование существующего kubeconfig**

```bash
cp ~/.kube/config ~/.kube/config.backup
```

**Шаг 4: Создание первого контекста**

```bash
# Создание директории для dev-кластера
mkdir -p ~/.kube/contexts/dev

# Копирование текущей конфигурации
cp ~/.kube/config ~/.kube/contexts/dev/config
```

---

### Основные команды

**Список доступных контекстов:**

```bash
kubeswitches list
```

**Пример вывода:**

```
Available contexts:
  - dev
  - stage
  - prod
```

**Переключение контекста:**

```bash
kubeswitches set dev
```

**Проверка текущего контекста:**

```bash
kubectl config current-context
```

**Просмотр конфигурации:**

```bash
kubectl config view
```

---

### Добавление нового кластера

**Шаг 1: Получение kubeconfig нового кластера**

```bash
# Пример: получение от администратора кластера
# или экспорт из существующей конфигурации
kubectl config view --raw --minify > new-cluster-config.yaml
```

**Шаг 2: Создание контекста в kubeswitches**

```bash
mkdir -p ~/.kube/contexts/new-cluster
cp new-cluster-config.yaml ~/.kube/contexts/new-cluster/config
```

**Шаг 3: Переключение на новый контекст**

```bash
kubeswitches set new-cluster
```

---

### Интеграция с оболочкой

**Bash/Zsh алиасы:**

```bash
# Добавление в ~/.bashrc или ~/.zshrc
alias ks='kubeswitches'
alias ksl='kubeswitches list'
alias kss='kubeswitches set'

# Функция для быстрого переключения
ksw() {
  kubeswitches set "$1"
  echo "Switched to: $(kubectl config current-context)"
}
```

**Использование:**

```bash
ksw dev    # Переключение на dev
ksw prod   # Переключение на prod
```

**Отображение текущего контекста в prompt:**

```bash
# Добавление в ~/.bashrc или ~/.zshrc
parse_kube_context() {
  if [ -f ~/.kube/config ]; then
    local context=$(kubectl config current-context 2>/dev/null)
    if [ -n "$context" ]; then
      echo " [$context]"
    fi
  fi
}

# Для bash
PS1='\u@\h:\w$(parse_kube_context)$ '

# Для zsh с oh-my-zsh
# Использовать плагин kubectx
```

---

### Синхронизация с cloud-провайдерами

**GKE (Google Kubernetes Engine):**

```bash
# Получение credentials для кластера
gcloud container clusters get-credentials cluster-name --zone zone --project project

# Сохранение как отдельный контекст
mkdir -p ~/.kube/contexts/gke-prod
cp ~/.kube/config ~/.kube/contexts/gke-prod/config
```

**Yandex Cloud Managed Kubernetes:**

```bash
# Обновление kubeconfig
yc managed-kubernetes cluster get-credentials --name cluster-name --folder-id folder-id

# Сохранение как отдельный контекст
mkdir -p ~/.kube/contexts/yandex-prod
cp ~/.kube/config ~/.kube/contexts/yandex-prod/config
```

**Локальный кластер (kubeadm/k3s/minikube):**

```bash
# kubeconfig обычно находится в ~/.kube/config
# Для переключения между кластерами используйте контексты

# Сохранение как отдельный контекст
mkdir -p ~/.kube/contexts/local-prod
cp ~/.kube/config ~/.kube/contexts/local-prod/config
```

---

## Additional Information

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| kubectl | 1.20+ | Для работы с кластерами |
| Bash/Zsh | 4.0+ | Для скриптов интеграции |

### Связанные темы

- **[kubectl](../Base/kubectl.md)** — основы работы с kubectl
- **[kubeconfig](../Base/kubeconfig.md)** — структура и использование kubeconfig
