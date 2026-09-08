# Kubetail: Одновременный мониторинг логов нескольких подов

## Определения

**Kubetail** (johanhaleby/kubetail) — инструмент командной строки (Bash-скрипт), предназначенный для агрегации логов из нескольких подов Kubernetes в один хронологический поток. Он позволяет отслеживать работу распределенных компонентов системы в реальном времени, используя цветовую маркировку для каждого источника.

На 2026 год важно различать два одноименных проекта:
1.  **johanhaleby/kubetail** (описывается здесь) — классический скрипт-обертка над `kubectl logs`.
2.  **kubetail-org/kubetail** — независимый проект с веб-интерфейсом, CLI на Go и агентом на Rust (v0.26.0).

Официальный репозиторий: [github.com/johanhaleby/kubetail](https://github.com/johanhaleby/kubetail).

**Актуальная версия:** v1.6.22 (2025/2026).

**Лицензия:** Apache-2.0. Звёзды: ~3.5k.

---

## Основные концепции

### Архитектура и принцип работы

Инструмент не требует установки серверных компонентов (агентов) в кластер. Логика работы строится на клиентской стороне:

```
Kubetail (клиентский Bash-скрипт)
    ↓
Идентификация подов по паттерну/меткам через Kubernetes API
    ↓
Запуск параллельных процессов kubectl logs -f для каждого пода
    ↓
Чтение STDOUT, добавление цветовых префиксов и объединение потоков
    ↓
Вывод в терминал пользователя
```

### Цветовое кодирование

Для визуального разделения потоков каждому поду присваивается уникальный цвет из палитры Xterm (по умолчанию используется цикл из 8 цветов). Это критически важно при отладке взаимодействий между микросервисами.

**Режимы цвета** (флаг `-k`):

| Значение | Описание |
| :--- | :--- |
| `pod` | Цветом выделяется только имя пода, текст лога — цвет терминала по умолчанию |
| `line` | Цветом выделяется вся строка (по умолчанию) |
| `false` | Отключение цветного вывода полностью |

**Пропуск цветов:** флаг `-z` позволяет исключить конкретные ID цветов (например, слишком темные), которые трудно читать на текущем фоне терминала.

**Показ индекса цвета:** флаг `-i true` (или переменная `KUBETAIL_SHOW_COLOR_INDEX=true`) выводит индекс цвета перед именем пода (например, `[3:my-pod-12341] some log`). Это полезно при проблемах с восприятием цветов (color blindness) и помогает точно определить, какой ID нужно исключить через `-z`.

### Интеграция с JQ (JSON-логи)

Современные версии поддерживают обработку JSON-логов "на лету" перед выводом в терминал (требуется установленный `jq`):

```bash
# Вывод только сообщения и уровня из JSON-структуры
kubetail my-app -j '.msg + " [" + .level + "]"'

# Фильтрация по severity
kubetail my-app -j 'select(.level == "error") | .msg'

# Извлечение timestamp и message
kubetail my-app -j '"[\(.timestamp)] \(.message)"'
```

### Фильтрация и подсветка

Kubetail сам по себе не имеет встроенных средств фильтрации или подсветки. Рекомендуемые инструменты:

- **iTerm2 (macOS):** непрерывная подсветка поисковых запросов, прокрутка, multitab-режим. Функция "Timeline" (`Cmd+Shift+E`) позволяет отобразить временную шкалу в локальном часовом поясе рядом с логами (обычно в UTC).
- **Multitail (fork):** форк [aks/kubetail](https://github.com/aks/kubetail) от Alana Stebbens добавляет расширенную конфигурацию и интеграцию с [multitail](https://www.vanheusden.com/multitail/) и [bash-lib](https://github.com/aks/bash-lib).

---

## Практические сценарии

### Установка

#### macOS / Linux (Homebrew — рекомендуется)

```bash
# Стандартная установка
brew install johanhaleby/kubetail/kubetail

# Установка с коротким именем 'kt'
brew install johanhaleby/kubetail/kubetail --with-short-names
# После обновления может потребоваться: compinit (для zsh)

# Установка последней неопубликованной версии (из main)
brew install --HEAD johanhaleby/kubetail/kubetail
```

#### Прямая загрузка (Linux / macOS)

```bash
sudo curl -L https://raw.githubusercontent.com/johanhaleby/kubetail/master/kubetail -o /usr/local/bin/kubetail
sudo chmod +x /usr/local/bin/kubetail
```

#### ASDF (менеджер версий)

```bash
asdf plugin-add kubetail https://github.com/janpieper/asdf-kubetail.git
asdf list-all kubetail          # просмотр доступных версий
asdf install kubetail <version> # установка конкретной версии
asdf global kubetail <version>  # установка глобальной версии
```

#### ZSH-плагины

**Antigen:**

```bash
# Добавьте в ~/.zshrc
antigen bundle johanhaleby/kubetail
```

**oh-my-zsh:**

```bash
cd ~/.oh-my-zsh/custom/plugins/
git clone https://github.com/johanhaleby/kubetail.git kubetail
# Добавьте в plugins в ~/.zshrc: plugins=( ... kubetail )
source ~/.zshrc
```

**zgen:**

```bash
# Добавьте в ~/.zshrc
zgen load johanhaleby/kubetail
# Затем: zgen reset && zgen save
```

#### Zsh-completion (автодополнение)

**macOS (zsh):**

```bash
curl -L https://raw.githubusercontent.com/johanhaleby/kubetail/master/completion/kubetail.zsh \
  -o /usr/local/share/zsh/site-functions/_kubetail
```

**Linux (bash):**

```bash
curl -L https://raw.githubusercontent.com/johanhaleby/kubetail/master/completion/kubetail.bash \
  -o ~/.bash_completion.d/kubetail.bash
# Добавьте в ~/.bashrc: source ~/.bash_completion.d/kubetail.bash
```

**Fish:**

```bash
curl -L https://raw.githubusercontent.com/johanhaleby/kubetail/master/completion/kubetail.fish \
  -o ~/.config/fish/completions/kubetail.fish
```

### Базовое использование и фильтрация

```bash
# Логи всех подов, имя которых содержит "api-gateway"
kubetail api-gateway

# Логи с ограничением вывода последних 50 строк из каждого пода
kubetail api-gateway --tail 50

# Исключение определенных цветов (например, 1 и 7)
kubetail api-gateway -z 1,7

# Опрос состояния подов с интервалом в 2 секунды (поиск новых подов)
kubetail api-gateway -i 2

# Несколько приложений одновременно (через запятую)
kubetail app1,app2

# Несколько приложений через пробел (RegularExpression)
kubetail "^app1|.*my-demo.*" --regex
```

### Режимы цвета

```bash
# Только имена подов цветом, текст — без цвета
kubetail my-app -k pod

# Все строки цветом (по умолчанию)
kubetail my-app -k line

# Без цвета полностью
kubetail my-app -k false

# Показать индексы цветов перед именами подов
kubetail my-app -i true
# Пример вывода: [3:my-app-abc123] 2026-09-01T10:00:00Z INFO Started
```

### Выбор по меткам и пространствам имен

```bash
# Использование селекторов меток (labels)
kubetail -l app=backend,env=prod

# Логи из всех пространств имен (Namespaces)
kubetail my-app --all-namespaces

# Логи из конкретного неймспейса
# Важно: флаг -n указывается ПОСЛЕ контейнера и приложения
kubetail my-app -c container1 -n staging
```

### Регулярные выражения и исключения

```bash
# Выбор подов по точному соответствию регулярному выражению
kubetail -r '^worker-[0-9]{2}$'

# Или через --regex
kubetail "^order-|.*payment.*" --regex

# Исключение конкретных подов из общего потока
kubetail microservice -E microservice-bad-node-1 -E microservice-debug
```

### Работа с мультиконтейнерными подами

```bash
# Логи конкретного контейнера (например, 'istio-proxy') во всех подах
kubetail my-app -c istio-proxy

# Логи нескольких конкретных контейнеров
kubetail my-app -c app-container -c istio-proxy

# Логи всех контейнеров во всех выбранных подах одновременно
kubetail my-app --all-containers
```

### Просмотр логов после перезагрузки (CrashLoopBackOff)

```bash
# Просмотр логов предыдущей (упавшей) инстанции контейнера
kubetail my-app --previous

# Постоянный мониторинг текущих логов вместе с предыдущими
kubetail my-app --previous --follow
```

### Сохранение конфигурации через переменные окружения

Настройки можно зафиксировать в `.bashrc` или `.zshrc`:

| Переменная | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `KUBETAIL_COLORS` | Количество используемых цветов | `8` |
| `KUBETAIL_NO_COLOR` | Отключить цветовую маркировку | `false` |
| `KUBETAIL_COLORED_OUTPUT` | Включить цветной вывод | `true` |
| `KUBETAIL_TIMESTAMP` | Добавлять временные метки в вывод | `true` |
| `KUBETAIL_SKIP_COLORS` | Список ID цветов для исключения | `none` |
| `KUBETAIL_SHOW_COLOR_INDEX` | Показывать индекс цвета перед именем пода | `false` |
| `KUBETAIL_JQ_SELECTOR` | Глобальный фильтр JQ для всех логов | `none` |
| `KUBETAIL_TAIL` | Количество строк с конца (аналог `--tail`) | все |
| `KUBETAIL_PREVIOUS` | Показывать логи предыдущего контейнера | `false` |
| `KUBETAIL_SINCE` | Показывать логи за последние N секунд | все |
| `KUBETAIL_NAMESPACE` | Пространство имен по умолчанию | все |
| `KUBETAIL_FOLLOW` | Следовать за логами (streaming) | `true` |
| `KUBETAIL_PREFIX` | Добавлять префикс с именем пода | `true` |
| `KUBETAIL_LINE_BUFFERED` | Буферизация по строкам | `false` |

### Просмотр справки

```bash
# Полный вывод справки
kubetail -h

# Все доступные флаги
kubetail --help
```

---

## Дополнительная информация

### Системные требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `kubectl` | Совместимая с кластером | Должен быть в PATH и настроен |
| Bash | 4.0+ | Используются ассоциативные массивы |
| `jq` | Любая | Опционально, для фильтрации JSON |
| ОС | Linux / macOS / WSL | Требуется поддержка POSIX |

### Сравнение с аналогами (состояние на 2026 год)

| Инструмент | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Kubetail (Bash)** | Максимальная простота, отсутствие бинарных файлов, гибкость фильтров. | Зависимость от Bash 4+, замедление на 100+ подах. |
| **Stern** | Написан на Go, экстремально быстрый, мощные шаблоны вывода. | Требует установки бинарного файла. |
| **Kubetail (Org)** | Полноценный Web UI, продвинутый поиск и алертинг. | Требует установки серверных агентов в кластер. |
| **Kail** | Удобен для динамического отслеживания новых ReplicaSet. | Менее гибкая цветовая палитра. |

### Типичные сценарии использования

1.  **Отладка распределенных транзакций:** одновременный просмотр логов цепочки микросервисов (Gateway -> Auth -> DB).
2.  **Мониторинг прогресса деплоя:** наблюдение за логами новых подов в процессе RollingUpdate.
3.  **Диагностика падений:** использование ключа `--previous` для быстрого анализа причин CrashLoopBackOff.
4.  **Фильтрация JSON-логов:** использование `-j` для удаления лишних полей и шума в структурированных логах.
5.  **Аудит безопасности:** мониторинг логов входа и действий пользователей в нескольких сервисах одновременно.
6.  **Мониторинг фоновых задач:** отслеживание Job и CronJob через `--previous` для анализа завершённых выполнений.

### Смотрите также

- [`kubectl logs`](../Troubleshooting/troubleshooting_overview.md) — базовые возможности логирования.
- [Централизованное логирование](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) — стратегии сбора логов в больших кластерах.
- [GitHub: johanhaleby/kubetail](https://github.com/johanhaleby/kubetail) — исходный код Bash-версии.
