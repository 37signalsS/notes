# kubeswitches

## Definitions

**`kubeswitches`** — утилита CLI для управления несколькими файлами `kubeconfig` и быстрого переключения между контекстами кластеров Kubernetes. Организует конфигурационные файлы для различных кластеров (например, `development`, `staging`, `production`) в отдельных подкаталогах, упрощая переключение активного `kubeconfig`.

---

## Basic Concepts

### Архитектура и принцип работы

`kubeswitches` работает по принципу хранения контекстов в отдельных файлах и их копирования:

1. **Хранение:** Каждый кластер хранится в отдельном файле `config` в своей поддиректории (например, `~/.kube/contexts/<name>/config`).
2. **Переключение:** При переключении контекста файл копируется в `~/.kube/config`.
3. **Изоляция:** Конфигурации кластеров не смешиваются, что снижает риск случайных ошибок при работе с кластерами.
4. **Совместимость:** Стандартные утилиты (`kubectl`, `helm`) продолжают работать с `~/.kube/config` без изменений.

### Структура каталогов

Требуется централизованная директория с подкаталогами для каждого контекста Kubernetes.

**Пример структуры:**

```text
~/.kube/contexts/
├── dev
│   └── config
├── stage
│   └── config
└── prod
    └── config
```

Каждый подкаталог содержит файл `config` с полным kubeconfig для соответствующего кластера.

### Переменная окружения

Необходимо определить переменную окружения `KUBESWITCH_CONTEXT_DIR`, указывающую на основную директорию с контекстами.

**Добавление в ~/.bashrc или ~/.zshrc:**

```bash
export KUBESWITCH_CONTEXT_DIR="$HOME/.kube/contexts"
```

**Применение изменений:**

```bash
source ~/.bashrc  # или source ~/.zshrc
```

### Необходимые компоненты

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **kubectl** | 1.20+ | Для работы с кластерами |
| **Bash/Zsh** | 4.0+ | Для скриптов интеграции |

### Сравнение с альтернативами и ограничения

| Инструмент | Подход | Преимущества | Недостатки и ограничения |
| :--- | :--- | :--- | :--- |
| **kubeswitches** | Отдельные файлы на кластер | Полная изоляция, простота | Копирование файлов (медленнее), нет синхронизации облачных конфигов, нет управления внутри одного файла |
| **kubectl config** | Единый файл с контекстами | Встроен в kubectl | Смешивание конфигураций, риск случайных изменений |
| **kubectx** | Управление контекстами в одном файле | Быстрое переключение | Риск случайных изменений |

---

## Practical Scenarios

### Установка

> ⚠️ **Примечание:** Проект `kubeswitches` малоизвестен. URL и команды могут требовать верификации перед использованием. Альтернатива — [kubectx](https://github.com/ahmetb/kubectx).

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

### Защита файлов kubeconfig

`config` файлы содержат чувствительные данные (токены, сертификаты).

```bash
chmod 600 ~/.kube/contexts/*/config
chmod 700 ~/.kube/contexts
```

> **Изоляция production-контекстов:** Production kubeconfig следует хранить на зашифрованных носителях или использовать менеджеры секретов (HashiCorp Vault, AWS Secrets Manager) вместо хранения в виде простых файлов.

### Основные команды

| Команда | Описание |
| :--- | :--- |
| `kubeswitches list` | Список доступных контекстов |
| `kubeswitches set <name>` | Переключение на контекст (копирует файл конфигурации) |
| `kubectl config current-context` | Проверка текущего контекста |
| `kubectl config view` | Просмотр конфигурации |

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

**Отображение текущего контекста в prompt (bash):**

```bash
parse_kube_context() {
  if [ -f ~/.kube/config ]; then
    local context=$(kubectl config current-context 2>/dev/null)
    if [ -n "$context" ]; then
      echo " [$context]"
    fi
  fi
}

PS1='\u@\h:\w$(parse_kube_context)$ '
```

### Обновление credentials (синхронизация с cloud-провайдерами)

При ротации credentials в облачных провайдерах (GKE, EKS, AKS) требуется вручную обновить файлы `config` в директориях контекстов, так как автоматической синхронизации нет:

```bash
# GKE
gcloud container clusters get-credentials cluster-name --zone zone
cp ~/.kube/config ~/.kube/contexts/gke-prod/config

# Yandex Cloud
yc managed-kubernetes cluster get-credentials --name cluster-name
cp ~/.kube/config ~/.kube/contexts/yandex-prod/config
```

---

## Additional Information

### Связанные документы

- **[kubeconfig](../../Operations/kubeconfig_and_connection.md)** — структура и использование kubeconfig
- **[Lens](../lens/definitions_and_concepts.md)** — GUI для управления несколькими кластерами

### Репозиторий и документация

- [GitHub: поиск kubeswitches](https://github.com/search?q=kubeswitches)
- Альтернатива: **[kubectx](https://github.com/ahmetb/kubectx)** — более популярный инструмент для управления контекстами.
