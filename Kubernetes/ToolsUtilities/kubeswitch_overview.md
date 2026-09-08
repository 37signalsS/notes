# Kubeswitch (switcher)

## Определения

**Kubeswitch** — это концепция и набор инструментов для эффективного управления множеством файлов `kubeconfig` и быстрого переключения между контекстами Kubernetes. Инструмент может быть представлен как простыми bash-скриптами (`kubeswitches`), так и продвинутыми утилитами (`switcher`), обеспечивающими изоляцию сессий терминала и интеграцию с внешними хранилищами секретов.

Основным инструментом в 2026 году является **switcher** (команда `switch`) от проекта `danielfoehrKn/kubeswitch` — Go-утилита, которая позволяет динамически объединять конфигурации из файловой системы, HashiCorp Vault и поддерживает exec-плагины для любых backend'ов.

**Терминология:**

- **Store** — источник kubeconfig-файлов: `filesystem`, `vault`, произвольный через exec-плагин.
- **Hook** — действие, выполняемое до/после поиска контекста (например, обновление токена Vault).
- **Alias** — короткое имя для длинного пути в Store (например, `pr` → `kubernetes/clusters/prod-east-1`).
- **Session isolation** — режим, при котором `KUBECONFIG` меняется только для текущего shell-процесса через временный файл в `KUBESWITCH_CONTEXT_DIR`.

## Когда использовать

| Ситуация | Рекомендация |
| :--- | :--- |
| 1–3 кластера, dev-машина | `kubectl config use-context` (встроенная команда) |
| 3–15 кластеров, нужны быстрые переключения | **kubectx + kubens** (минималистично, POSIX) |
| 10+ кластеров, разные среды (dev/stage/prod) | **switcher (Kubeswitch)** с `filesystem` store |
| Команда, kubeconfig'и лежат в Vault/S3/корпоративном Secret Manager | **switcher** + соответствующий store / exec-плагин |
| CI/CD-агенты, единичный кластер на джобу | `KUBECONFIG=... kubectl ...` (без сторонних утилит) |
| Нужна изоляция между вкладками терминала | Только `switcher` (поддерживает session isolation) |

## Основные концепции

### Принцип работы

Основная идея заключается в декомпозиции монолитного файла `~/.kube/config` на отдельные конфигурации:
1. **Хранение:** Каждый кластер или группа контекстов хранится в отдельном файле в структурированной директории или во внешнем хранилище.
2. **Переключение:** При смене контекста инструмент динамически обновляет переменную окружения `KUBECONFIG` для текущей сессии, часто используя временные файлы для изоляции.
3. **Изоляция:** Это предотвращает "смешивание" конфигураций и минимизирует риск случайного выполнения команд в `production` вместо `development`.

### Архитектура switcher

```
┌─────────────────────────────────────────────────────────────┐
│  Shell session (bash/zsh/fish)                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ alias switch='source <(switcher init)'               │  │
│  │ → функция switch() подменяет $KUBECONFIG на лету      │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │ (KUBECONFIG=/tmp/kubeswitch/ctx-XXXXX)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  switcher (Go binary)                                       │
│  ┌────────────┐  ┌────────────┐  ┌───────────────────────┐  │
│  │ filesystem │  │ vault      │  │ custom exec plugin    │  │
│  │ store      │  │ store      │  │ (gopass, 1Password,…) │  │
│  └────────────┘  └────────────┘  └───────────────────────┘  │
│       │                │                  │                 │
│       ▼                ▼                  ▼                 │
│  ~/.kube/contexts/  vault read       ./my-kube-provider      │
│  ├── dev/          kubernetes/...   --list                   │
│  ├── stage/                                                │
│  └── prod/                                                 │
└─────────────────────────────────────────────────────────────┘
```

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

Каждый подкаталог содержит автономный файл конфигурации (полный `apiVersion: v1, kind: Config`).

**Альтернативная раскладка** — один файл на контекст в плоской директории (полезно, если `store.paths` указывает на wildcard):

```text
~/.kube/contexts/
├── dev-cluster.yaml
├── stage-cluster.yaml
└── prod-cluster.yaml
```

### Изоляция терминалов (продвинутый уровень)

Утилита `switcher` поддерживает изоляцию на уровне сессии:
- При выполнении `switch` создается временный файл в директории, указанной в `KUBESWITCH_CONTEXT_DIR` (по умолчанию `/tmp/kubeswitch/`).
- Переменная `KUBECONFIG` обновляется только для текущего процесса shell.
- Это позволяет одновременно работать с разными кластерами в разных вкладках терминала без конфликтов.

## Практические сценарии

### Установка

**Вариант 1: утилита switcher (рекомендуется)**

```bash
# macOS (Homebrew)
brew install danielfoehrkn/switch/switch

# Linux (бинарник)
curl -L https://github.com/danielfoehrKn/kubeswitch/releases/latest/download/switcher_linux_amd64 -o switcher
chmod +x switcher
sudo mv switcher /usr/local/bin/

# Проверка
switcher --version
```

**Вариант 2: ручные скрипты (legacy)**

```bash
git clone https://github.com/danielfoehrKn/kubeswitches
cd kubeswitches
go build -o kubeswitches ./cmd/kubeswitches
sudo mv kubeswitches /usr/local/bin/
```

**Вариант 3: минимальная альтернатива — kubectx + kubens (POSIX, нет Go-зависимостей)**

```bash
# Установка через Homebrew/Linuxbrew
brew install kubectx

# Установка вручную
sudo curl -L https://github.com/ahmetb/kubectx/releases/latest/download/kubectx -o /usr/local/bin/kubectx
sudo curl -L https://github.com/ahmetb/kubectx/releases/latest/download/kubens    -o /usr/local/bin/kubens
sudo chmod +x /usr/local/bin/kubectx /usr/local/bin/kubens
```

### Первоначальная настройка

Для корректной работы `switch` необходимо инициализировать оболочку.

**Bash / Zsh:**

Добавьте в `~/.bashrc` или `~/.zshrc`:

```bash
# Инициализация (создает alias 'switch' и функции интеграции)
source <(switcher init zsh)   # или bash

# Автоподгрузка fzf (обязателен для интерактивного режима)
[ -f ~/.fzf.bash ] && source ~/.fzf.bash
```

**Fish:**

В Fish `switch` является зарезервированным словом, поэтому используется команда `kubeswitch` (рекомендуется алиас `s`):
1. Скачайте `kubeswitch.fish` из релизов GitHub.
2. Добавьте в `~/.config/fish/config.fish`:

```fish
source path/to/kubefwd.fish  # (если используется)
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
  # Локальная файловая система
  - kind: filesystem
    paths:
      - "~/.kube/contexts"
    # Опционально: фильтр по подкаталогу
    # paths:
    #   - "~/.kube/contexts/prod"

  # HashiCorp Vault
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

**Использование хуков (hooks)**

Позволяют выполнять действия перед поиском (например, обновление токенов):

```yaml
hooks:
  - name: vault-login-check
    type: pre-search
    execution:
      command: "vault token lookup > /dev/null 2>&1 || vault login -method=oidc"
    interval: 1h
```

**Типы хуков:**

| Тип | Когда срабатывает | Пример использования |
| :--- | :--- | :--- |
| `pre-search` | До вывода списка контекстов | `vault login`, продление SSO-токена |
| `post-search` | После выбора контекста | Логирование, уведомление |
| `pre-exec` | Перед выполнением команды через `switch exec` | Аудит, проверка прав |

### Основные команды

| Команда | Описание |
| :--- | :--- |
| `switch` | Запуск интерактивного поиска (требуется `fzf`) |
| `switch <name>` | Быстрое переключение на контекст по имени |
| `switch -` | Вернуться к предыдущему контексту |
| `switch alias add <alias>=<name>` | Создать короткое имя для длинного пути в Vault/FS |
| `switch alias list` | Показать все алиасы |
| `switch alias remove <alias>` | Удалить алиас |
| `switch exec "*-prod-*" -- kubectl get nodes` | Выполнить команду во всех кластерах, подходящих под glob-маску |
| `switch launch` | Открыть выбранный контекст в Lens/k9s (если настроено) |
| `switch delete` | Удалить временный файл и сбросить `KUBECONFIG` |

### Переменные окружения

| Переменная | Назначение | По умолчанию |
| :--- | :--- | :--- |
| `KUBESWITCH_CONTEXT_DIR` | Каталог для временных kubeconfig'ов | `/tmp/kubeswitch/` |
| `KUBESWITCH_GLOBAL=true` | Отключить session isolation, писать в `~/.kube/config` напрямую | `false` |
| `KUBESWITCH_CONFIG` | Путь к switch-config.yaml | `~/.kube/switch-config.yaml` |
| `KUBESWITCH_DISABLE_INDEXER=true` | Отключить фоновую индексацию store | `false` |
| `KUBESWITCH_CACHE_TTL` | TTL локального кэша (например, `1h`) | из конфига |
| `KUBECONFIG` | Стандартная переменная kubectl — подменяется switcher'ом | `~/.kube/config` |

### Защита конфигурационных файлов

```bash
# Установка прав доступа для локальных файлов
chmod 700 ~/.kube/contexts
chmod 600 ~/.kube/contexts/*/config
```

Каталог должен иметь `700` (доступ только владельцу), файлы внутри — `600` (чтение/запись только владельцем). Это предотвращает чтение токенов другими пользователями на shared-хостах и jump-серверах.

### Добавление нового кластера

**Экспорт из текущего окружения:**

```bash
# Minify-конфиг для одного контекста
kubectl config view --raw --minify --flatten > ~/.kube/contexts/new-cluster/config
chmod 600 ~/.kube/contexts/new-cluster/config
```

**Из RKE/K3s (узел кластера):**

```bash
# RKE2
sudo cp /etc/rancher/rke2/rke2.yaml ~/.kube/contexts/rke2-prod/config
sed -i 's/127.0.0.1/<external-ip-or-fqdn>/' ~/.kube/contexts/rke2-prod/config
chmod 600 ~/.kube/contexts/rke2-prod/config

# K3s
sudo k3s kubectl config view --raw > ~/.kube/contexts/k3s-prod/config
```

**Из Rancher (downstream-кластеры):**

```bash
# UI: Cluster Management → кластер → Kubeconfig File → Copy
# Сохранить в файл
mkdir -p ~/.kube/contexts/rancher-downstream
nano ~/.kube/contexts/rancher-downstream/config
chmod 600 ~/.kube/contexts/rancher-downstream/config
```

**Создание контекста «с нуля» (для CI/CD или нового кластера):**

```bash
mkdir -p ~/.kube/contexts/ci-runner
cat > ~/.kube/contexts/ci-runner/config <<'EOF'
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: BASE64_CA==
    server: https://api.k8s.internal:6443
  name: ci-runner
contexts:
- context:
    cluster: ci-runner
    user: ci-runner
    namespace: ci
  name: ci-runner
current-context: ci-runner
users:
- name: ci-runner
  user:
    token: sha256~...  # ServiceAccount token
EOF
chmod 600 ~/.kube/contexts/ci-runner/config
```

### Интеграция с Vault (командный kubeconfig)

**Подготовка секрета в Vault (KV v2):**

```bash
# Положить kubeconfig в Vault
vault kv put secret/kubernetes/clusters/prod kubeconfig=@~/.kube/contexts/prod/config

# Проверить
vault kv get -format=json secret/kubernetes/clusters/prod | jq '.data.data.kubeconfig'
```

**Проверка доступа:**

```bash
# 1. Токен валиден
vault token lookup

# 2. switcher читает конфиг
switch   # в интерактивном меню должен появиться prod
```

### Использование exec-плагинов (gopass, 1Password, custom)

Если kubeconfig'и хранятся в gopass или 1Password, можно подключить их через `kind: exec`:

```yaml
kubeconfigStores:
  - kind: exec
    config:
      # Скрипт должен выводить JSON-массив путей к kubeconfig-файлам
      command: "gopass-jsonapi"
      args:
        - "list"
        - "--flat"
        - "kubeconfigs"
    # Каждый путь интерпретируется как отдельный kubeconfig-файл
```

Подробная спецификация формата вывода — в [официальной документации switcher](https://github.com/danielfoehrKn/kubeswitch/blob/master/docs/exec_stores.md).

### Массовое выполнение команд (switch exec)

```bash
# Получить nodes из всех prod-кластеров
switch exec "*prod*" -- kubectl get nodes -o wide

# Перезагрузить daemonset во всех stage-кластерах
switch exec "stage-*" -- kubectl rollout restart daemonset/fluentd

# Проверить версию kubectl-плагинов на всех dev
switch exec "dev-*" -- kubectl version --short
```

Команда выполняется **последовательно** (не параллельно) — для параллельного запуска используйте внешние инструменты (`xargs -P`, `parallel`, `kubectl-mtb`).

## Диагностика и решение проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `switch` не найден | Не выполнена инициализация в `.rc` файле | Проверьте `source <(switcher init ...)` в конфиге оболочки. |
| `switch: command not found` после `source` | Используется `bash` вместо `zsh` (или наоборот) | Выполните `switcher init bash` для bash-сессии. |
| `fzf not found` | Не установлен `fzf` | `brew install fzf` или `apt install fzf`. Можно использовать `switch <name>` напрямую без fzf. |
| Контекст не меняется в других вкладках | Включена изоляция сессий | Это ожидаемое поведение `switcher`. Используйте `KUBESWITCH_GLOBAL=true` если нужна глобальная смена (не рекомендуется). |
| Ошибка доступа к Vault | Истек токен или неверный адрес | Выполните `vault login` или проверьте `vaultAPIAddress` в `switch-config.yaml`. |
| `permission denied` на временный файл | `KUBESWITCH_CONTEXT_DIR` на NFS с `no_root_squash` | Используйте `KUBESWITCH_CONTEXT_DIR=/tmp/kubeswitch-$USER` или локальный диск. |
| Медленный поиск | Слишком много файлов или медленный API Vault | Включите кэширование (`cache.enabled: true`) в конфигурации Store. |
| `indexer crashed` в логах | Старая версия switcher не поддерживает новый store | Обновите `switcher` до последней версии. |
| После `switch prod` команда идёт в dev | Имя алиаса совпадает с другим store, неоднозначность | Используйте префиксы (`prod-east`, `prod-west`) или `switch alias rm` для конфликтующих. |
| `open /tmp/kubeswitch/...: no such file or directory` | Удалён `KUBESWITCH_CONTEXT_DIR` | Создайте заново: `mkdir -p $KUBESWITCH_CONTEXT_DIR && chmod 700 $KUBESWITCH_CONTEXT_DIR` |

### Диагностические команды

```bash
# Где switcher ищет конфиг
switcher --config

# Какой store активен и сколько контекстов
switcher --show-stores

# Текущая переменная KUBECONFIG (внутри switch-сессии)
echo $KUBECONFIG
cat $KUBECONFIG

# Список всех контекстов (без переключения)
kubectl config get-contexts

# Проверить, что fzf видит список
KUBESWITCH_DISABLE_INDEXER=true switch
```

## Безопасность

- **Права на файлы:** всегда `chmod 700` на директории и `chmod 600` на `config`-файлы. На shared-серверах (jump-host, bastion) используйте отдельного пользователя без sudo.
- **Секреты вне файлов:** предпочитайте exec-плагины с короткоживущими токенами (OIDC, `kubelogin`) вместо статических токенов в kubeconfig. Если используется статический токен ServiceAccount, настройте алерт на истечение.
- **Токены в Vault:** не логируйте и не копируйте в clipboard kubeconfig с токеном. Используйте `kubectl config view --minify` (без `--raw`) для шеринга имени контекста.
- **Tmp-директория:** убедитесь, что `KUBESWITCH_CONTEXT_DIR` находится на диске с `noexec` отключенным (нужен для `kubectl`), но с `nosuid` включенным, и не на shared-разделе (например, `/tmp` на многопользовательском хосте).
- **Alias'ы от непроверенных источников:** не импортируйте чужие `switch-config.yaml` — alias может резолвиться в произвольный путь.
- **Аудит переключений:** включайте `post-search` hook с записью в audit-лог (`audit.log` Loki/journald) для production-кластеров, чтобы отслеживать, кто и когда получил доступ.

## Производительность и масштабирование

| Число кластеров | Рекомендация |
| :--- | :--- |
| 1–10 | `filesystem` store, `cache.enabled: false` (мгновенный старт) |
| 10–50 | `filesystem` store, `cache.enabled: true, ttl: 1h` |
| 50–200 | Разделить store по средам (`dev`, `prod`), использовать алиасы |
| 200+ | Vault/exec-store с TTL-кэшированием, выделить namespace-ы в switcher'е (через `KUBESWITCH_NAMESPACE` или отдельные бинарники) |

**Тюнинг:**

- `KUBESWITCH_DISABLE_INDEXER=true` — отключает фоновую индексацию, ускоряет старт, но замедляет поиск (особенно с fzf).
- `KUBESWITCH_CACHE_TTL=24h` — снижает нагрузку на Vault при частом использовании.
- Параллельный запуск команд на 50+ кластерах: используйте `kubectl-mtb` или Ansible AWX вместо `switch exec` (последний выполняет последовательно).

## Дополнительная информация

### Сравнение инструментов

| Параметр | Ручные скрипты | kubectx | switcher (Kubeswitch) |
| :--- | :--- | :--- | :--- |
| **Изоляция** | Глобальная | Глобальная | На уровне сессии (Terminal-safe) |
| **Источники** | Локальные папки | Файл `~/.kube/config` | Vault, FS, exec-плагины, Hooks |
| **Интерактивность** | Низкая | fzf (опционально) | Высокая (встроенный fzf-интерфейс) |
| **Масштабируемость** | Плохая | Средняя | Отличная (индексация, кэш) |
| **Зависимости** | Только `kubectl` | `kubectl`, `fzf` (опц.) | `kubectl`, `fzf` (обяз.), Go-runtime не нужен |
| **Платформы** | Любой POSIX | Linux, macOS, WSL | Linux, macOS, WSL2, Windows (частично) |
| **Exec-плагины** | Нет | Нет | Да (OIDC, gopass, 1Password) |
| **Активная разработка** | Нет | Поддерживается | Активная (danielfoehrKn, 2025–2026) |

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **kubectl** | 1.24+ | Рекомендуется для актуальных API |
| **fzf** | 0.30+ | Обязателен для интерактивного режима `switch` |
| **Vault CLI** | 1.10+ | Если используется Vault Store |
| **Go runtime** | — | Не требуется (switcher — статический бинарник) |

### Чеклист внедрения для команды

1. **Определить матрицу кластеров:** среды (dev/stage/prod) × регионы/области.
2. **Выбрать store:** `filesystem` для начала, `vault` при наличии инфраструктуры Vault.
3. **Подготовить структуру** `~/.kube/contexts/<env>/<cluster>/config`.
4. **Раздать конфиг через Ansible/Rsalt/Chef** для воспроизводимости (опционально).
5. **Инициализировать** `switcher init <shell>` в dotfiles команды.
6. **Документировать соглашение об именовании:** `<env>-<region>-<cluster>` (например, `prod-eu-west-1`).
7. **Настроить алиасы** для типовых переходов (`switch alias add p=prod-eu-west-1`).
8. **Добавить hooks** для продления SSO/Vault-токенов.
9. **Обучить команду** принципу session isolation (не пугаться, что в других вкладках другой кластер).
10. **Настроить аудит** через `post-search` hook.

### Смотрите также

- **[Kubeconfig: Подключение к кластеру](../Operations/kubeconfig_and_connection.md)** — структура и параметры файлов конфигурации.
- **[Lens — практические сценарии](../lens/practical_scenarios.md)** — графический интерфейс для управления кластерами.
- **[k9s: Терминальный UI для Kubernetes](../k9s.md)** — альтернативный способ работы с кластерами.
- **[Vault: Обзор](../../../Vault/overview.md)** — использование Vault как backend для kubeconfig.
- **[Official Kubeswitch Repo](https://github.com/danielfoehrKn/kubeswitch)** — документация по расширенным Store и кастомным хукам.
