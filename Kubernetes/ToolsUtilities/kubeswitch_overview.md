# Kubeswitch

## Определения

**Kubeswitch** — это концепция и набор инструментов для эффективного управления множеством файлов `kubeconfig` и быстрого переключения между контекстами Kubernetes. Инструмент может быть представлен как простыми bash-скриптами (`kubeswitches`), так и продвинутыми утилитами (`switcher`), обеспечивающими изоляцию сессий терминала и интеграцию с внешними хранилищами секретов.

## Основные концепции

### Принцип работы

Основная идея заключается в декомпозиции монолитного файла `~/.kube/config` на отдельные конфигурации:
1.  **Хранение:** Каждый кластер или группа контекстов хранится в отдельном файле в структурированной директории (например, `~/.kube/contexts/`).
2.  **Переключение:** При смене контекста инструмент либо копирует нужный файл в `~/.kube/config`, либо динамически обновляет переменную окружения `KUBECONFIG` для текущей сессии.
3.  **Изоляция:** Это предотвращает "смешивание" конфигураций и минимизирует риск случайного выполнения команд в `production` вместо `development`.

### Структура каталогов

Для ручного управления или использования простых скриптов рекомендуется следующая структура:

```text
~/.kube/contexts/
├── dev
│   └── config
├── stage
│   └── config
└── prod
    └── config
```
# → Каждый подкаталог содержит автономный файл конфигурации.

### Изоляция терминалов (Advanced)

Современные версии (например, `danielfoehrKn/kubeswitch`) поддерживают изоляцию на уровне сессии:
- При выполнении `switch` создается временный файл в `/tmp/` или `KUBESWITCH_CONTEXT_DIR`.
- Переменная `KUBECONFIG` обновляется только для текущего процесса shell.
- Это позволяет одновременно работать с разными кластерами в разных вкладках терминала.

## Практические сценарии

### Установка

**Вариант 1: Современная утилита (switcher/switch):**
```bash
# macOS
brew install danielfoehrkn/switch/switch

# Linux (Binary)
curl -L https://github.com/danielfoehrKn/kubeswitch/releases/latest/download/switcher_linux_amd64 -o switcher
chmod +x switcher
sudo mv switcher /usr/local/bin/
# → switcher установлен в /usr/local/bin/
```

**Вариант 2: Ручной скрипт (kubeswitches):**
```bash
git clone <URL_репозитория_скриптов>
cd kubeswitches
go build -o kubeswitches ./cmd/kubeswitches
sudo mv kubeswitches /usr/local/bin/
```

### Первоначальная настройка и переменные

Добавьте в `~/.bashrc` или `~/.zshrc`:
```bash
# Директория для хранения контекстов
export KUBESWITCH_CONTEXT_DIR="$HOME/.kube/contexts"

# Инициализация switcher (если используется)
source <(switcher init zsh) # или bash
```

### Защита конфигурационных файлов

Файлы `kubeconfig` содержат чувствительные данные (токены, сертификаты).
```bash
# Установка прав доступа
chmod 700 ~/.kube/contexts
chmod 600 ~/.kube/contexts/*/config
# → Права доступа ограничены только текущим пользователем
```

### Добавление нового кластера

**Из текущего конфига:**
```bash
# Экспорт текущего активного контекста в отдельный файл
kubectl config view --raw --minify > ~/.kube/contexts/new-cluster/config
# → Файл создан в директории контекста
```

**Через облачные провайдеры:**
```bash
# GKE (Google Cloud)
gcloud container clusters get-credentials cluster-name --zone zone
cp ~/.kube/config ~/.kube/contexts/gke-prod/config

# Yandex Cloud
yc managed-kubernetes cluster get-credentials --name cluster-name
cp ~/.kube/config ~/.kube/contexts/yandex-prod/config
```

### Интеграция с оболочкой (Bash/Zsh)

**Функция для быстрого переключения (ручной метод):**
```bash
ksw() {
  local target_dir="$HOME/.kube/contexts/$1"
  if [ -d "$target_dir" ]; then
    cp "$target_dir/config" ~/.kube/config
    echo "Switched to: $1"
    echo "Current context: $(kubectl config current-context)"
  else
    echo "Context $1 not found in $HOME/.kube/contexts/"
  fi
}
```

**Отображение контекста в Prompt (Bash):**
```bash
parse_kube_context() {
  if [ -f ~/.kube/config ]; then
    local context=$(kubectl config current-context 2>/dev/null)
    [ -n "$context" ] && echo " [$context]"
  fi
}
PS1='\u@\h:\w$(parse_kube_context)$ '
```

### Интеграция с HashiCorp Vault

`switcher` позволяет подтягивать конфиги напрямую из Vault без сохранения на диск:
```yaml
# ~/.kube/switch-config.yaml
vault:
  address: https://vault.example.com
  stores:
    - path: "kubernetes/clusters"
      kind: "kv2"
```

## Дополнительная информация

### Сравнение подходов

| Параметр | Ручной (скрипты) | switcher (Advanced) |
| :--- | :--- | :--- |
| **Механизм** | Копирование файлов | Динамический KUBECONFIG |
| **Изоляция** | Глобальная (на все окна) | На уровне сессии терминала |
| **Источники** | Только локальные папки | Vault, GKE, EKS, AKS, Хуки |
| **Скорость** | Зависит от FS | Индексация и кэширование |

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **kubectl** | 1.20+ | Обязателен |
| **fzf** | Последняя | Для интерактивного поиска в switch |
| **Bash/Zsh** | 4.0+ | Для скриптов интеграции |

### Смотрите также

- **[kubeconfig](../../Operations/kubeconfig_and_connection.md)** — детальное описание структуры файлов конфигурации.
- **[Lens](../lens/definitions_and_concepts.md)** — графический интерфейс для управления множеством кластеров.
- **[Official Kubeswitch Repo](https://github.com/danielfoehrKn/kubeswitch)** — документация по расширенным Store и кастомным хукам.
