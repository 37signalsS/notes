# Управление приоритетами пакетов в Apt (Pinning)

## Определения

**Pinning (Приоритизация пакетов)** — механизм Apt для гибкого управления выбором источника и версии пакета. Позволяет назначать приоритеты репозиториям или конкретным версиям, влияя на решение Apt при установке и обновлении.

**Приоритет (Pin Priority)** — числовое значение (от -1 до 990+), присваиваемое каждой версии пакета. Определяет предпочтительность версии при установке. Apt всегда выбирает версию с наивысшим приоритетом.

**Кандидат на установку (Candidate Version)** — версия пакета, которую Apt выберет при выполнении `apt-get install` или `apt upgrade`. Определяется по максимальному приоритету.

## Основные понятия

### Принцип выбора пакета Apt

**По умолчанию** Apt устанавливает пакет с максимальной версией из доступных репозиториев. При равных версиях приоритет отдаётся репозиторию, объявленному первым в конфигурации.

**Механизм pinning** изменяет это поведение, позволяя вручную назначать приоритеты на основе:

- Версии пакета
- Происхождения (origin)
- Дистрибутива (archive)
- Кодового имени (codename)
- Компонента (component)
- Архитектуры

### Файлы конфигурации

| Файл | Назначение |
| :--- | :--- |
| `/etc/apt/preferences` | Основной файл приоритетов (устаревший) |
| `/etc/apt/preferences.d/` | Директория для отдельных правил (рекомендуемый) |
| `/etc/apt/sources.list` | Источники репозиториев |
| `/etc/apt/sources.list.d/` | Дополнительные источники |

**Важно:** Файлы в `/etc/apt/preferences.d/` должны иметь расширение `.pref` для обработки.

### Стандартные значения приоритетов

| Приоритет | Значение |
| :--- | :--- |
| **> 1000** | Безусловная установка, допустим downgrade |
| **990–1000** | Приоритет для целевого релиза (по умолчанию) |
| **500–989** | Стандартный приоритет для обычных репозиториев |
| **100–499** | Приоритет для установленных версий и backports |
| **1–99** | Низкий приоритет, не для автоматической установки |
| **0** | Пакет установлен, но не будет обновляться |
| **< 0** | Запрет установки (отклонение версии) |

### Правила вычисления приоритета

1. **Приоритет из `preferences`** — если правило совпадает, используется указанное значение
2. **Приоритет по умолчанию** — если нет правил, используется `APT::Default-Release` (обычно 500)
3. **Установленная версия** — получает приоритет 100, если не переопределено
4. **Backports** — по умолчанию получают приоритет 100

## Практические сценарии

### Просмотр приоритетов

```bash
# Показать приоритеты всех репозиториев
apt-cache policy

# Показать приоритеты конкретного пакета
apt-cache policy nginx

# Подробная информация о кандидате
apt-cache madison nginx
```

**Пример вывода `apt-cache policy nginx`:**

```
nginx:
  Установлен: 1.18.0-0ubuntu1.4
  Кандидат:   1.20.2-1~focal
  Таблица версий:
     1.20.2-1~focal 500
        500 https://nginx.org/packages/ubuntu focal/nginx amd64 Packages
 *** 1.18.0-0ubuntu1.4 100
        100 /var/lib/dpkg/status
     1.18.0-0ubuntu1 500
        500 http://archive.ubuntu.com/ubuntu focal-updates/main amd64 Packages
```

### Варианты условий Pin

| Условие | Синтаксис | Пример |
| :--- | :--- | :--- |
| **Версия** | `Pin: version <pattern>` | `Pin: version 1.28.2*` |
| **Происхождение** | `Pin: release o=<origin>` | `Pin: release o=nginx` |
| **Дистрибутив** | `Pin: release a=<archive>` | `Pin: release a=stable` |
| **Кодовое имя** | `Pin: release n=<codename>` | `Pin: release n=noble` |
| **Компонент** | `Pin: release c=<component>` | `Pin: release c=main` |
| **Архитектура** | `Pin: release b=<arch>` | `Pin: release b=amd64` |
| **Комбинация (AND)** | `Pin: release o=nginx,a=stable,n=noble` | Все условия должны совпасть |

### Пример 1: Приоритизация всего репозитория

Для предпочтения всех пакетов из определённого репозитория, даже если их версии ниже.

```bash
# Создать файл /etc/apt/preferences.d/my-repo.pref
sudo tee /etc/apt/preferences.d/my-repo.pref << 'EOF'
Package: *
Pin: origin "My Private Repo"
Pin-Priority: 990
EOF

# Обновить кэш
sudo apt-get update
```

| Поле | Значение |
| :--- | :--- |
| `Package: *` | Правило для всех пакетов |
| `Pin: origin "..."` | Идентификатор репозитория (из `apt-cache policy`) |
| `Pin-Priority: 990` | Высокий приоритет |

### Пример 2: Приоритизация конкретного пакета

Для «замораживания» версии определённого пакета из конкретного репозитория.

```bash
# Создать файл /etc/apt/preferences.d/nginx-pinning.pref
sudo tee /etc/apt/preferences.d/nginx-pinning.pref << 'EOF'
Package: nginx
Pin: origin "My Private Repo"
Pin-Priority: 1001
EOF
```

Приоритет **1001** гарантирует установку `nginx` из указанного репозитория, даже если это приведёт к понижению версии (downgrade).

### Пример 3: Запрет установки пакета из репозитория

```bash
# Создать файл /etc/apt/preferences.d/block-nginx.pref
sudo tee /etc/apt/preferences.d/block-nginx.pref << 'EOF'
Package: nginx
Pin: origin "nginx.org"
Pin-Priority: -1
EOF
```

Это правило блокирует установку `nginx` из репозитория с `Origin` "nginx.org".

### Пример 4: Предпочтение стабильной версии (Debian)

Для использования стабильной версии с возможностью установки отдельных пакетов из testing/unstable:

```bash
# /etc/apt/preferences.d/debian-pinning.pref
# Приоритет для stable
Package: *
Pin: release a=stable
Pin-Priority: 900

# Приоритет для testing (ниже)
Package: *
Pin: release a=testing
Pin-Priority: 500

# Приоритет для unstable (ещё ниже)
Package: *
Pin: release a=unstable
Pin-Priority: 100

# Отдельный пакет из testing
Package: firefox
Pin: release a=testing
Pin-Priority: 950
```

### Пример 5: Использование backports (Ubuntu/Debian)

Backports по умолчанию имеют приоритет 100. Для автоматического использования:

```bash
# /etc/apt/preferences.d/backports.pref
Package: *
Pin: release a=focal-backports
Pin-Priority: 500
```

Или для конкретного пакета:

```bash
# /etc/apt/preferences.d/libreoffice-backport.pref
Package: libreoffice*
Pin: release a=focal-backports
Pin-Priority: 600
```

### Пример 6: Комбинированные условия

```bash
# /etc/apt/preferences.d/complex-pinning.pref
# Только пакеты nginx из stable репозитория nginx.org
Package: nginx
Pin: release o=nginx,a=stable,n=noble
Pin-Priority: 1001

# Все пакеты из security-репозитория
Package: *
Pin: release a=focal-security
Pin-Priority: 950
```

### Пример 7: Временное понижение версии (Downgrade)

```bash
# Запретить обновление до проблемной версии
Package: problematic-package
Pin: version 2.0.*
Pin-Priority: -1

# Разрешить только версию 1.x
Package: problematic-package
Pin: version 1.9.*
Pin-Priority: 1001
```

## Дополнительная информация

### Применение изменений

После создания или модификации файлов в `/etc/apt/preferences.d/`:

```bash
# Обновить кэш
sudo apt-get update

# Проверить приоритеты
apt-cache policy <package-name>

# Симуляция установки (без фактической установки)
apt-get install --dry-run <package-name>
```

### Отладка и диагностика

```bash
# Показать, почему выбрана конкретная версия
apt-get -o Debug::pkgProblemResolver=1 install <package-name>

# Подробный вывод при обновлении
apt-get -o Debug::pkgAcquire=1 update

# Проверка синтаксиса файлов preferences
apt-cache policy | head -20
```

### APT::Default-Release

Глобальная настройка приоритета по умолчанию в `/etc/apt/apt.conf.d/`:

```bash
# /etc/apt/apt.conf.d/99default-release
APT::Default-Release "stable";
```

Это устанавливает приоритет 990 для релиза `stable` по умолчанию.

### Распространённые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Pinning ignored** | Неправильный `Origin` | Проверить через `apt-cache policy` |
| **Неверный приоритет** | Конфликт правил | Использовать более специфичные условия |
| **Файл не читается** | Нет расширения `.pref` | Переименовать файл |
| **Downgrade не работает** | Приоритет < 1001 | Установить приоритет > 1000 |

### Best Practices

1. **Используйте отдельные файлы** для каждого правила в `/etc/apt/preferences.d/`
2. **Давайте файлам понятные имена** с расширением `.pref`
3. **Тестируйте изменения** с `apt-cache policy` перед установкой
4. **Избегайте глобальных правил** `Package: *` без необходимости
5. **Документируйте причины** pinning в комментариях файлов
