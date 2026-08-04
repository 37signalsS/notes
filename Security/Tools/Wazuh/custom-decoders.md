# Декодеры в Wazuh: структура, типы и кастомная настройка

## Определения

**Декодер (Decoder)** — XML-описание, предназначенное для разбора (парсинга) сырых логов и извлечения из них структурированных данных (IP, пользователи, действия). 

**Процесс обработки логов**:
1.  **Декодирование**: Извлечение полей с помощью декодеров.
2.  **Анализ**: Применение правил к извлеченным полям для создания алертов.

**Типы декодеров**:
*   **Родительский (Root)**: Определяет общий формат лога (например, syslog, nginx, json). Фильтрует события по `program_name` или `prematch`.
*   **Дочерний (Child)**: Связан с родителем через тег `<parent>`. Извлекает конкретные поля из сообщения, уже опознанного родителем. Позволяет создавать цепочки разбора для сложных логов.

## Основные концепции

### Ключевые поля XML-синтаксиса

| Тег | Описание |
| :--- | :--- |
| `<program_name>` | Фильтрует логи по имени программы в Syslog-заголовке. Поддерживает PCRE2. |
| `<prematch>` | Проверяет наличие статической части лога для активации декодера. |
| `<regex>` | Извлекает данные с помощью регулярных выражений (рекомендуется PCRE2). |
| `<order>` | Назначает имена извлеченным полям (статические: `srcip`, `user`; динамические: `myapp.session`). |
| `<accumulate>` | Связывает события по ID (например, сессии), перенося поля из первых логов в последующие. |
| `<fts>` | Generate Alert on First Time Seen (первое появление события). |
| `<plugin_decoder>` | Использует специализированные плагины (например, `JSON_Decoder`) для сложных форматов. |
| `<use_own_name>` | Заставляет дочерний декодер использовать свое имя в алертах вместо родительского. |
| `<offset>` | Атрибут для `prematch` и `regex` (например, `after_parent`), ускоряющий парсинг за счет пропуска уже обработанных частей. |

### Типы логов (<type>)

Тег `<type>` указывает базовый формат лога, что критично для корректной связи с категориями правил (`<category>`).

**С Syslog-заголовком (дата, хост, программа):**
1.  **syslog**: Стандартные системные и прикладные логи.
2.  **firewall**: Логи межсетевых экранов (iptables, Cisco ASA).
3.  **ids**: События систем обнаружения вторжений (Snort, Suricata).
4.  **host-information**: Метрики хоста (CPU, память).
5.  **windows**: Логи Windows Event Log.

**Без Syslog-заголовка (анализ всей строки):**
6.  **web-log**: Логи веб-серверов (Apache, Nginx).
7.  **squid**: Логи прокси-сервера Squid.
8.  **ossec**: Кастомные логи с произвольным форматом.

## Практические сценарии

### 1. Декодирование CSV-логов PostgreSQL

PostgreSQL часто пишет логи в формате CSV, который сложно парсить напрямую. Рекомендуемый подход — конвертация в Syslog-подобный вид на стороне агента.

#### Шаг 1: Настройка агента (`agent.conf`)
Добавьте блок для сбора CSV-логов с использованием `out_format`:

```xml
<agent_config>
  <localfile>
    <location>/var/log/postgresql/postgresql-*.csv</location>
    <log_format>syslog</log_format>
    <out_format>$(timestamp) $(hostname) postgresql: $(log)</out_format>
  </localfile>
</agent_config>
```

#### Шаг 2: Создание декодера (`postgresql_custom.xml`)
Создайте файл в `/var/ossec/etc/decoders/`. Логика строится на иерархии родитель-ребенок.

```xml
<!-- Родитель: фильтрация по имени программы -->
<decoder name="postgresql">
  <program_name>postgresql</program_name>
</decoder>

<!-- Дочерние декодеры для извлечения полей -->
<decoder name="postgresql-fields">
  <parent>postgresql</parent>
  <!-- Извлечение пользователя -->
  <regex type="pcre2">\d+-\d+-\d+\s+\d+:\d+:\d+\.\d+.+?,[^,](.+?)",</regex>
  <order>srcuser</order>
</decoder>

<decoder name="postgresql-fields">
  <parent>postgresql</parent>
  <!-- Извлечение IP-адреса источника -->
  <regex type="pcre2">\d+-\d+-\d+\s+\d+:\d+:\d+\.\d+.+?,[^,]*,[^,]*,[^,]*,"(\S+):</regex>
  <order>srcip</order>
</decoder>

<decoder name="postgresql-fields">
  <parent>postgresql</parent>
  <!-- Извлечение типа команды (command_tag) -->
  <regex type="pcre2">\d+-\d+-\d+\s+\d+:\d+:\d+\.\d+.+?,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,"(.+?)"?,</regex>
  <order>command_tag</order>
</decoder>
```

### 2. Расширение стандартного декодера auditd

Стандартный декодер `auditd` в Wazuh парсит ограниченное число аргументов `execve`. Для глубокого анализа команд (например, длинных цепочек аргументов `a6`–`a10`) требуется модификация.

#### Шаг 1: Исключение дефолтного декодера
В `ossec.conf` менеджера добавьте исключение в блок `<ruleset>`:

```xml
<ruleset>
  <decoder_exclude>ruleset/decoders/0040-auditd_decoders.xml</decoder_exclude>
</ruleset>
```

#### Шаг 2: Создание кастомного декодера
Скопируйте содержимое оригинального файла в `/var/ossec/etc/decoders/0040-auditd_decoders.xml` и добавьте новые поля:

```xml
<decoder name="auditd-syscall">
  <parent>auditd</parent>
  <regex offset="after_regex">a8="(\.+)" </regex>
  <order>audit.execve.a8</order>
</decoder>

<decoder name="auditd-syscall">
  <parent>auditd</parent>
  <regex offset="after_regex">a9="(\.+)" </regex>
  <order>audit.execve.a9</order>
</decoder>
```

## Дополнительная информация

### Рекомендации
- **Отладка**: Используйте утилиту `/var/ossec/bin/wazuh-logtest` для проверки того, как декодер разбирает тестовую строку лога.
- **Приоритеты**: Wazuh сначала загружает декодеры из `ruleset/decoders/`, а затем из `etc/decoders/`. При использовании `decoder_exclude` вы берете полное управление на себя.

### См. также
- [auditd: аудит системных вызовов](../../../Linux/SystemAdministration/Logging/auditd.md)
- [Wazuh: обзор SIEM](../wazuh.md)
- [Автоматизация Wazuh через Ansible](./ansible-automation-per-agent.md)
