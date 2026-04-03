# kubeswitches usage

## Definitions

**kubeswitches usage** — практические сценарии установки, настройки и переключения между контекстами Kubernetes.

---

## Basic Concepts

### Архитектура работы

kubeswitches работает по принципу копирования файлов:

1. Каждый кластер хранится в `~/.kube/contexts/<name>/config`
2. При переключении файл копируется в `~/.kube/config`
3. Стандартные утилиты (`kubectl`, `helm`) работают с `~/.kube/config` без изменений

### Необходимые компоненты

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| kubectl | 1.20+ | Для работы с кластерами |
| Bash/Zsh | 4.0+ | Для скриптов интеграции |

> **Настройка окружения** описана в [index.md](./index.md).

---

## Practical Scenarios

### Установка

> ⚠️ **Примечание:** kubeswitches — малоизвестный проект. URL и команды могут требовать верификации.

**Ручная установка (Linux/macOS):**

```bash
curl -LO <актуальный_URL_бинарного_файла>
chmod +x kubeswitches
sudo mv kubeswitches /usr/local/bin/
```

**Сборка из исходников:**

```bash
git clone <актуальный_URL_репозитория>
cd kubeswitches
go build -o kubeswitches ./cmd/kubeswitches
sudo mv kubeswitches /usr/local/bin/
```

---

### Первоначальная настройка

После установки:

```bash
# Создание директории для контекстов
mkdir -p ~/.kube/contexts

# Резервное копирование существующего kubeconfig
cp ~/.kube/config ~/.kube/config.backup

# Создание первого контекста
mkdir -p ~/.kube/contexts/dev
cp ~/.kube/config ~/.kube/contexts/dev/config
```

Переменная окружения и структура каталогов описаны в [index.md](./index.md).

---

### Основные команды

> ⚠️ Команды приведены на основе общей документации проекта и требуют верификации.

| Команда | Описание |
| :--- | :--- |
| `kubeswitches list` | Список доступных контекстов |
| `kubeswitches set <name>` | Переключение на контекст |
| `kubectl config current-context` | Проверка текущего контекста |
| `kubectl config view` | Просмотр конфигурации |

---

### Добавление нового кластера

```bash
# Экспорт конфигурации из существующего kubeconfig
kubectl config view --raw --minify > new-cluster-config.yaml

# Создание контекста
mkdir -p ~/.kube/contexts/new-cluster
cp new-cluster-config.yaml ~/.kube/contexts/new-cluster/config

# Переключение
kubeswitches set new-cluster
```

---

### Интеграция с оболочкой

**Bash/Zsh алиасы:**

```bash
alias ks='kubeswitches'
alias ksl='kubeswitches list'
alias kss='kubeswitches set'

# Функция для быстрого переключения
ksw() {
  kubeswitches set "$1"
  echo "Switched to: $(kubectl config current-context)"
}
```

**Отображение текущего контекста в prompt:**

```bash
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
```

---

### Синхронизация с cloud-провайдерами

Процедура обновления credentials описана в [operations.md](./operations.md).

---

## Additional Information

### Связанные документы

- **[kubeswitches index](./index.md)** — основные понятия и настройка окружения
- **[Операции](./operations.md)** — безопасность и обновление credentials
- **[kubeconfig](../../Operations/kubeconfig_and_connection.md)** — структура kubeconfig
