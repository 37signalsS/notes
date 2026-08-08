# Kubeswitch

## Определения

**Kubeswitch** — это концепция и набор инструментов для эффективного управления множеством файлов `kubeconfig` и быстрого переключения между контекстами Kubernetes. Инструмент может быть представлен как простыми bash-скриптами (`kubeswitches`), так и продвинутыми утилитами (`switcher`), обеспечивающими изоляцию сессий терминала и интеграцию с внешними хранилищами секретов.

Основным инструментом в 2026 году является **switcher** (команда `switch`), который позволяет динамически объединять конфигурации из файловой системы, HashiCorp Vault и облачных провайдеров.

## Основные концепции

### Принцип работы

Основная идея заключается в декомпозиции монолитного файла `~/.kube/config` на отдельные конфигурации:
1.  **Хранение:** Каждый кластер или группа контекстов хранится в отдельном файле в структурированной директории или во внешнем хранилище.
2.  **Переключение:** При смене контекста инструмент динамически обновляет переменную окружения `KUBECONFIG` для текущей сессии, часто используя временные файлы для изоляции.
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

### Изоляция терминалов (Продвинутый уровень)

Утилита `switcher` (danielfoehrKn/kubeswitch) поддерживает изоляцию на уровне сессии:
- При выполнении `switch` создается временный файл в директории, указанной в `KUBESWITCH_CONTEXT_DIR` (по умолчанию обычно `/tmp/kubeswitch/`).
- Переменная `KUBECONFIG` обновляется только для текущего процесса shell.
- Это позволяет одновременно работать с разными кластерами в разных вкладках терминала без конфликтов.

## Практические сценарии

### Установка

**Вариант 1: Утилита switcher (рекомендуется):**
```bash
# macOS
brew install danielfoehrkn/switch/switch

# Linux (Binary)
curl -L https://github.com/danielfoehrKn/kubeswitch/releases/latest/download/switcher_linux_amd64 -o switcher
chmod +x switcher
sudo mv switcher /usr/local/bin/
# → switcher установлен в /usr/local/bin/
```

**Вариант 2: Ручные скрипты (legacy):**
```bash
git clone <URL_репозитория_скриптов>
cd kubeswitches
go build -o kubeswitches ./cmd/kubeswitches
sudo mv kubeswitches /usr/local/bin/
```

### Первоначальная настройка

Для корректной работы `switch` необходимо инициализировать оболочку.

**Bash / Zsh:**
Добавьте в `~/.bashrc` или `~/.zshrc`:
```bash
# Инициализация (создает alias 'switch' и функции интеграции)
source <(switcher init zsh) # или bash
```

**Fish:**
В Fish `switch` является зарезервированным словом, поэтому используется команда `kubeswitch` (рекомендуется алиас `s`).
1. Скачайте `kubeswitch.fish` из релизов GitHub.
2. Добавьте в `~/.config/fish/config.fish`:
```fish
source path/to/kubeswitch.fish
alias s="kubeswitch"
```

### Продвинутая конфигурация

Настройки хранятся в `~/.kube/switch-config.yaml`.

**Пример конфигурации с локальным хранилищем и Vault:**
```yaml
kind: SwitchConfig
version: v1alpha1
kubeconfigStores:
  - kind: filesystem
    paths:
      - "~/.kube/contexts"
  - kind: vault
    paths:
      - "kubernetes/clusters/production"
    config:
      vaultAPIAddress: "https://vault.example.com:8200"
      vaultKeyKubeconfig: "kubeconfig"
    cache:
      enabled: true
      ttl: 12h
```

**Использование хуков (Hooks):**
Позволяют выполнять действия перед поиском (например, обновление токенов).
```yaml
hooks:
  - name: vault-login-check
    type: pre-search
    execution:
      command: "vault token lookup > /dev/null || vault login -method=oidc"
    interval: 1h
```

### Основные команды

| Команда | Описание |
| :--- | :--- |
| `switch` | Запуск интерактивного поиска (требуется `fzf`) |
| `switch <name>` | Быстрое переключение на контекст по имени |
| `switch -` | Вернуться к предыдущему контексту |
| `switch alias add <alias>=<name>` | Создать короткое имя для длинного пути в Vault/FS |
| `switch exec "*-prod-*" -- kubectl get nodes` | Выполнить команду во всех кластерах, подходящих под маску |

### Защита конфигурационных файлов

```bash
# Установка прав доступа для локальных файлов
chmod 700 ~/.kube/contexts
chmod 600 ~/.kube/contexts/*/config
# → Права доступа ограничены только текущим пользователем
```

### Добавление нового кластера

**Экспорт из текущего окружения:**
```bash
kubectl config view --raw --minify > ~/.kube/contexts/new-cluster/config
```

**Облачные провайдеры:**
```bash
# Yandex Cloud
yc managed-kubernetes cluster get-credentials --name cluster-name --file ~/.kube/contexts/yandex-prod/config

# GKE
gcloud container clusters get-credentials cluster-name --zone zone
cp ~/.kube/config ~/.kube/contexts/gke-prod/config
```

## Диагностика и решение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `switch` не найден | Не выполнена инициализация в `.rc` файле | Проверьте `source <(switcher init ...)` в конфиге оболочки. |
| Контекст не меняется в других вкладках | Включена изоляция сессий | Это ожидаемое поведение `switcher`. Используйте `KUBESWITCH_GLOBAL=true` если нужна глобальная смена (не рекомендуется). |
| Ошибка доступа к Vault | Истек токен или неверный адрес | Выполните `vault login` или проверьте `vaultAPIAddress` в `switch-config.yaml`. |
| Медленный поиск | Слишком много файлов или медленный API Vault | Включите кэширование (`cache.enabled: true`) в конфигурации Store. |

## Дополнительная информация

### Сравнение инструментов

| Параметр | Ручные скрипты | kubectx | switcher (Kubeswitch) |
| :--- | :--- | :--- | :--- |
| **Изоляция** | Глобальная | Глобальная | На уровне сессии (Terminal-safe) |
| **Источники** | Локальные папки | Файл `~/.kube/config` | Vault, FS, GKE, EKS, Hooks |
| **Интерактивность** | Низкая | fzf (опционально) | Высокая (встроенный fzf-интерфейс) |
| **Масштабируемость** | Плохая | Средняя | Отличная (индексация, кэш) |

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **kubectl** | 1.24+ | Рекомендуется для актуальных API |
| **fzf** | Последняя | Обязателен для интерактивного режима `switch` |
| **Vault CLI** | 1.10+ | Если используется Vault Store |

### Смотрите также

- **[kubeconfig](../../Operations/kubeconfig_and_connection.md)** — структура и параметры файлов конфигурации.
- **[Lens](../lens/practical_scenarios.md)** — графический интерфейс для управления кластерами.
- **[Official Kubeswitch Repo](https://github.com/danielfoehrKn/kubeswitch)** — документация по расширенным Store и кастомным хукам.
