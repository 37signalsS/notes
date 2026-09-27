# Декодеры в Wazuh: структура, типы и кастомная настройка

## Определения

**Декодер (Decoder)** — XML- или YAML-описание, предназначенное для разбора (парсинга) сырых логов и извлечения из них структурированных данных. Декодеры превращают неструктурированный текст в набор именованных полей (IP, пользователи, ID сессий), которые затем анализируются правилами.

**Нормализация нестандартных источников** — процесс настройки SIEM для работы с самописным или сильно кастомизированным ПО, логи которого Wazuh не умеет разбирать «из коробки». Без нормализации такие события отображаются в сыром виде без заполнения ключевых полей (Source IP, Username и др.).

**Wazuh Common Schema (WCS)** — унифицированная схема именования полей в Wazuh 5.0+, обеспечивающая кросс-платформенную корреляцию. Все декодеры (XML и YAML) должны маппить извлеченные данные в поля WCS (`source.ip`, `user.name`, `event.action`, `process.name` и др.).

**Процесс обработки события**:
1.  **Pre-decoding**: Автоматическое извлечение стандартных полей (timestamp, hostname, program_name) ядром Wazuh.
2.  **Decoding**: Поиск подходящего родительского декодера и последующее извлечение полей дочерними или сиблинг-декодерами.
3.  **Analysis**: Сопоставление извлеченных полей с критериями правил для генерации алертов.

## Жизненный цикл декодера

1.  **Создание (Draft)**: Написание декодера в `local_decoder.xml` (XML) или через Content Manager API (YAML в 5.0+). Использование уникального имени и правильной иерархии.
2.  **Тестирование**: Валидация через `wazuh-logtest` на эталонных сырых логах без перезапуска менеджера.
3.  **Code Review**: Проверка на дублирование имен, жадные regex, отсутствие захвата чувствительных данных.
4.  **Деплой**: Применение через GitOps-пайплайн с атомарной валидацией.
5.  **Мониторинг**: Отслеживание количества декодированных событий, ошибок парсинга и производительности через `wazuh.log`.
6.  **Тюнинг или деактивация**: При проблемах производительности или избыточной логике — рефакторинг или отключение.

## Основные концепции

### Расположение файлов и ID

Для внесения изменений рекомендуется использовать локальные файлы:

| Версия | Декодеры | Правила |
| :--- | :--- | :--- |
| **Wazuh 4.x** | `/var/ossec/etc/decoders/local_decoder.xml` | `/var/ossec/etc/rules/local_rules.xml` |
| **Wazuh 5.x** | Через Content Manager API или YAML-файлы в индексе | `/var/wazuh-manager/etc/rules/local_rules.xml` или Sigma YAML |

Подробная информация о синтаксисе правил, иерархии и корреляции: **[Правила корреляции и обнаружения в Wazuh](./wazuh-rules.md)**.

### Иерархия декодеров

Wazuh использует древовидную структуру для оптимизации производительности:

| Тип декодера | Описание и назначение |
| :--- | :--- |
| **Родительский (Root)** | Служит "якорем". Фильтрует поток логов по `program_name` или `prematch`. Если родитель не подошел, вся ветка его потомков игнорируется. |
| **Дочерний (Child)** | Связан с родителем через `<parent>`. Извлекает конкретные данные. Не может иметь собственных детей (глубина вложенности ограничена 1 уровнем). |
| **Сиблинг (Sibling)** | Группа декодеров с общим родителем. Используются, когда одно приложение пишет логи разных форматов (например, "Login success" и "Query failed"). |

### Ключевые теги синтаксиса (XML)

| Тег | Назначение |
| :--- | :--- |
| `<prematch>` | Быстрый поиск статической подстроки для активации декодера. |
| `<regex>` | Извлечение данных. Атрибут `type="pcre2"` включает современный движок регулярных выражений. |
| `<order>` | Присвоение имен захваченным группам из `regex`. Рекомендуется использовать стандартные имена (`srcip`, `srcuser`) для интеграции с базовыми правилами. |
| `<accumulate />` | Механизм "памяти". Если декодировано поле `id`, Wazuh сохраняет значения `srcip`, `srcuser` и др. на 120 секунд для последующих событий с тем же ID. |
| `<use_own_name>` | Позволяет использовать имя дочернего декодера в поле `decoder.name` вместо родительского. |
| `<offset>` | Управляет позиционированием regex: `after_regex` (после предыдущего regex), `after_parent`, `after_prematch`. |
| `<program_name>` | Фильтр по названию программы в заголовке лога. Работает только для Syslog-подобных логов. |
| `<type>` | Тип лога: `syslog`, `firewall`, `ids`, `web-log`, `squid`, `windows`, `host-information`. Влияет на предобработку. |
| `<decoder_exclude>` | Исключение стандартного декодера из обработки (используется в `ossec.conf`). |

### Специализированные декодеры

*   **JSON_Decoder**: Встроенный плагин для автоматического разбора JSON-структур. Не требует описания каждого поля через regex.
*   **Plug-in decoders**: Использование внешних библиотек для сложных бинарных или проприетарных форматов (PF_Decoder, SymantecWS_Decoder, SonicWall_Decoder).

### Декодеры в Wazuh 5.0 (YAML-формат)

В Wazuh 5.0+ декодеры переместились из XML-файлов в YAML-конфигурации, управляемые через **Content Manager API**. Это упрощает поддержку и добавляет строгую типизацию через **Wazuh Common Schema (WCS)**.

#### Сравнение XML и YAML

| XML | YAML |
| :--- | :--- |
| `<parent>syslog</parent>` | `parents: [decoder/syslog/0]` |
| `<prematch>sshd</prematch>` | `check: $process.name == 'sshd'` |
| `<regex type="pcre2">User '(\S+)'</regex>` + `<order>user</order>` | `parse|message: ["User <user.name>"]` |
| `<program_name>sshd</program_name>` | `check: $process.name == 'sshd'` |
| `<accumulate />` | `accumulate: true` |
| Извлечение в `srcip`, `dstip` | Маппинг в `source.ip`, `destination.ip` через `map` |

#### Пример YAML-декодера (Wazuh 5.0)

```yaml
name: decoder/sshd-auth-failure/0
id: "550e8400-e29b-41d4-a716-446655440000"
enabled: true
parents:
  - decoder/syslog/0
metadata:
  title: "SSH authentication failure"
  description: "Extracts failed SSH login attempts."
  author: "SOC Team"
  date: "2026-01-15"
  compatibility:
    - "Wazuh 5.0"
check: $process.name == 'sshd'
normalize:
  - parse|message:
      - "<~>: Failed password for <user.name> from <source.ip> port <source.port>"
    map:
      - event.action: authentication-failure
      - event.outcome: failure
      - event.category: array_append(authentication)
```

*Примечание: В Wazuh 5.0 поле `event.original` автоматически заполняется исходным логом, поэтому декодеры фокусируются на извлечении структурированных полей.*

## Практические сценарии

### 1. Декодирование JSON-логов современных приложений

Большинство Cloud-native приложений пишут логи в JSON. Разбор таких логов максимально упрощен.

```xml
<decoder name="my-json-app">
  <parent>json</parent> <!-- Использование встроенного JSON-родителя -->
  <prematch type="pcre2">"app_name":\s*"auth-service"</prematch>
  <use_own_name>yes</use_own_name>
</decoder>
```
*Примечание: Все поля JSON будут автоматически добавлены в событие с префиксом или без него, в зависимости от настроек менеджера.*

### 2. Сиблинг-декодеры для сложного приложения

Если приложение `myapp` пишет два типа логов:
1. `User 'admin' logged in`
2. `Action 'delete' performed on 'file1'`

```xml
<decoder name="myapp">
  <program_name>myapp</program_name>
</decoder>

<!-- Сиблинг 1: Вход -->
<decoder name="myapp-login">
  <parent>myapp</parent>
  <prematch>logged in</prematch>
  <regex type="pcre2">User '(\S+)'</regex>
  <order>srcuser</order>
</decoder>

<!-- Сиблинг 2: Действие -->
<decoder name="myapp-action">
  <parent>myapp</parent>
  <prematch>performed on</prematch>
  <regex type="pcre2">Action '(\S+)' performed on '(\S+)'</regex>
  <order>action, target_file</order>
</decoder>
```

### 3. Расширение стандартного декодера auditd

Для глубокого анализа аргументов `execve` (например, `a6`–`a10`) в `auditd`.

#### Шаг 1: Исключение оригинального файла
В `ossec.conf` менеджера:
```xml
<ruleset>
  <decoder_exclude>ruleset/decoders/0040-auditd_decoders.xml</decoder_exclude>
</ruleset>
```

#### Шаг 2: Кастомизация в `/var/ossec/etc/decoders/`
```xml
<decoder name="auditd-syscall">
  <parent>auditd</parent>
  <!-- Использование offset="after_regex" для последовательного поиска -->
  <regex offset="after_regex">a8="([^"]+)"</regex>
  <order>audit.execve.a8</order>
</decoder>
```

### 4. Нормализация логов самописного ПО

Сценарий: приложение `example` пишет лог в формате:
`Dec 5 22:45:01 MyHost example[12345]: User 'admin' logged from '192.168.1.10'`

**Шаг 1: Создание декодера (`local_decoder.xml`)**
```xml
<decoder name="example">
  <program_name>^example</program_name>
</decoder>

<decoder name="example-child">
  <parent>example</parent>
  <regex>User '(\w+)' logged from '(\d+\.\d+\.\d+\.\d+)'</regex>
  <order>user, srcip</order>
</decoder>
```

**Шаг 2: Создание правила (`local_rules.xml`)**
```xml
<group name="custom_rules_example,">
  <rule id="100010" level="3">
    <program_name>example</program_name>
    <description>User logged in to example application</description>
  </rule>
</group>
```

### 5. Декодирование логов Nginx (Sysadmin)

Стандартный формат access log Nginx с дополнительным полем `request_time`:

```
192.168.1.10 - - [15/Jan/2026:10:23:45 +0000] "GET /api/v1/users HTTP/1.1" 200 1234 "-" "curl/7.68.0" request_time=0.045
```

```xml
<decoder name="nginx">
  <program_name>nginx</program_name>
</decoder>

<decoder name="nginx-access">
  <parent>nginx</parent>
  <prematch type="pcre2">^(\d+\.\d+\.\d+\.\d+)</prematch>
  <regex type="pcre2">^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+) \S+" (\d+) (\d+) "[^"]*" "[^"]*" request_time=([\d\.]+)</regex>
  <order>srcip, timestamp, action, url, status, size, request_time</order>
</decoder>
```

### 6. Декодирование логов sudo

Логи sudo содержат информацию о пользователе, команде и хосте:

```
Jan 15 10:30:00 web01 sudo: pam_unix(sudo:session): session opened for user root by ubuntu(uid=0)
```

```xml
<decoder name="sudo">
  <program_name>sudo</program_name>
</decoder>

<decoder name="sudo-session">
  <parent>sudo</parent>
  <prematch>session opened</prematch>
  <regex type="pcre2">session opened for user (\S+) by (\S+)\(uid=(\d+)\)</regex>
  <order>dstuser, srcuser, srcuid</order>
</decoder>
```

### 7. Декодирование многострочных логов (Java/Python)

Для stacktrace и многострочных логов используйте `offset="after_regex"`:

```xml
<decoder name="java-app">
  <program_name>java</program_name>
</decoder>

<decoder name="java-exception">
  <parent>java-app</parent>
  <prematch>Exception:</prematch>
  <regex offset="after_regex">([\w\.]+Exception): (.*)</regex>
  <order>exception_class, exception_message</order>
</decoder>
```

### 8. Detection as Code: CI/CD пайплайн для декодеров

Декодеры должны проходить тот же жизненный цикл, что и код:

```yaml
# .gitlab-ci.yml или GitHub Actions
stages:
  - lint
  - test
  - deploy

xml-lint:
  stage: lint
  script:
    - xmllint --noout decoders/local_decoder.xml
  only:
    - merge_requests

decoder-test:
  stage: test
  script:
    - docker run --rm -v $PWD/decoders:/decoders wazuh/wazuh-logtest:latest /test-logs/
  only:
    - merge_requests

deploy-decoder:
  stage: deploy
  script:
    - ansible-playbook playbooks/deploy-decoder.yml
  only:
    - main
```

### 10. Декодеры и правила для MikroTik

MikroTik RouterOS отправляет логи в формате syslog с префиксом в виде имени устройства. Для нормализации этих логов в Wazuh создайте родительский декодер `mikrotik` и дочерние декодеры для конкретных событий (вход, выход, смена конфигурации).

#### Формат сырого лога

```
sep/01/2026 10:20:15 router1,info,account user admin logged in from 192.168.1.50 via winbox
```

Поля: `timestamp`, `hostname`, `severity`, `subsystem`, `message`.

#### Декодеры

```xml
<!-- /var/wazuh-manager/etc/decoders/local_decoder.xml -->

<!-- Микротик: успешный вход -->
<decoder name="mikrotik-login">
  <prematch>^\w+,\w+,\w+ user \S+ logged in from</prematch>
  <regex>^\w+,\w+,\w+ user (\S+) logged in from (\S+) via (\S+)</regex>
  <order>srcuser,srcip,mikrotik.login_method</order>
</decoder>

<!-- Микротик: выход -->
<decoder name="mikrotik-logout">
  <prematch>^\w+,\w+,\w+ user \S+ logged out</prematch>
  <regex>^\w+,\w+,\w+ user (\S+) logged out</regex>
  <order>srcuser</order>
</decoder>

<!-- Микротик: базовый декодер для catch-all -->
<decoder name="mikrotik">
  <prematch>^\w+,\w+</prematch>
</decoder>
```

#### Правила

```xml
<!-- /var/wazuh-manager/etc/rules/local_rules.xml -->
<group name="mikrotik,syslog,">

  <!-- Успешный вход -->
  <rule id="100101" level="5">
    <decoded_as>mikrotik-login</decoded_as>
    <description>Mikrotik: User $(srcuser) logged in from $(srcip) via $(mikrotik.login_method)</description>
    <group>authentication_success,</group>
  </rule>

  <!-- Выход -->
  <rule id="100102" level="3">
    <decoded_as>mikrotik-logout</decoded_as>
    <description>Mikrotik: User $(srcuser) logged out</description>
    <group>authentication_logout,</group>
  </rule>

  <!-- Изменение конфигурации -->
  <rule id="100105" level="7">
    <decoded_as>mikrotik</decoded_as>
    <match>changed by|configuration changed</match>
    <description>Mikrotik: Configuration changed</description>
    <group>config_change,</group>
  </rule>

</group>
```

После внесения изменений перезапустите менеджер:

```bash
sudo systemctl restart wazuh-manager
```

#### Валидация через `wazuh-logtest`

Проверьте работу декодера без перезапуска:

```bash
sudo /var/wazuh-manager/bin/wazuh-logtest -t alert -u 001
# Вставьте сырую строку лога MikroTik и проверьте Phase 2 (Decoding) и Phase 3 (Rule matching)
```

#### Отладка с помощью wazuh-logtest

Утилита `/var/wazuh-manager/bin/wazuh-logtest` — основной инструмент для проверки результатов нормализации без риска остановки менеджера.

**Запуск и использование**:
1. Выполните команду: `sudo /var/wazuh-manager/bin/wazuh-logtest`.
2. Вставьте сырую строку лога в интерактивном режиме.
3. Проанализируйте вывод:
   - **Phase 1 (Pre-decoding)**: Правильно ли извлечены `hostname` и `program_name`.
   - **Phase 2 (Decoding)**: Какой декодер сработал и какие поля были извлечены (`user`, `srcip`).
   - **Phase 3 (Filtering/Rule matching)**: Сработало ли нужное правило и какой уровень алерта присвоен.

**Расширенное использование**:
```bash
# Проверка конкретного алерта
sudo /var/wazuh-manager/bin/wazuh-logtest -t alert

# Вставка JSON алерта из alerts.log → вывод с полями "rule", "decoder", "srcuser"
sudo /var/wazuh-manager/bin/wazuh-logtest -t alert -u 001

# Подробный вывод процесса сопоставления
sudo /var/wazuh-manager/bin/wazuh-logtest -v
```

**Совет**: Используйте флаг `-v` для получения подробного лога процесса сопоставления и `-t` для тестирования эталонных логов без запуска полного конвейера.

## Применение изменений

После того как `wazuh-logtest` подтвердил корректность работы декодеров и правил, необходимо перезапустить сервис для применения конфигурации:

```bash
systemctl restart wazuh-manager
```

*Внимание: Перед перезапуском убедитесь, что в XML-файлах нет синтаксических ошибок, так как это может привести к сбою запуска менеджера.*

## Производительность и масштабирование

- **Ограничение иерархии**: Глубина вложенности декодеров ограничена 1 уровнем (parent → child). При проектировании используйте сиблинги вместо глубоких деревьев.
- **PCRE2 и `<prematch>`**: Всегда используйте `<prematch>` перед `<regex>`. Простой поиск подстроки в десятки раз быстрее компиляции и выполнения регулярного выражения.
- **Кэширование `<accumulate>`**: Механизм `accumulate` удержижит состояние в памяти 120 секунд. При высокой нагрузке (>5000 EPS) ограничьте количество декодеров с `accumulate` критичными сценариями.
- **CDB vs Regex**: Для проверки 100+ значений (IP-списки, хеши) используйте CDB-списки. Поиск в CDB выполняется за O(1), regex — за O(n).

## Управление ложными срабатываниями декодеров

| Ошибка / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **Декодер не срабатывает** | Неверный `program_name` или `prematch` не совпадает с началом лога | Проверьте `wazuh-logtest` Phase 1. Убедитесь, что `program_name` учитывает Syslog-заголовок. |
| **Извлечены неверные поля** | Жадный regex или неверный порядок `<order>` | Используйте нежадные квантификаторы `.*?`. Проверьте количество захватов в regex. |
| **Ложное срабатывание правила** | Слишком широкий `prematch` или извлечены лишние поля | Уточните `prematch`. Добавьте `<field>` в правило для фильтрации по контексту. |
| **Высокий CPU на Manager** | Слишком много regex без `prematch` или `accumulate` на массовых событиях | Перенесите проверки в CDB-списки. Добавьте `<prematch>`. Отключите `accumulate` для низкоприоритетных декодеров. |
| **Дублирующиеся алерты** | Два декодера-сиблинга извлекли одно и то же событие | Уточните `prematch` у каждого сиблинга. Используйте `use_own_name` для идентификации источника. |
| **Поле не маппится в WCS** | В Wazuh 5.0 используется нестандартное имя поля | Переименуйте поле в `<order>` на стандартное WCS (например, `source.ip` вместо `srcip`). |
| **Многострочный лог разбит** | Отсутствует multiline-сборка в Logcollector | Настройте `<log_format>multi-line-regex</log_format>` в `ossec.conf` перед декодированием. |

## Edge Cases

- **Бинарные данные в логах**: Включите `<ignore_binaries>yes</ignore_binaries>` в `ossec.conf`, чтобы предотвратить сбой декодера на не-JSON бинарных вставках.
- **Жадное отрицание**: Избегайте паттернов вида `.*error.*` без ограничений — они захватывают всю строку. Используйте `.*?error.*?` или явные границы.
- **Дублирование ID декодеров**: В Wazuh 5.0+ YAML-декодеры используют UUID. Для XML-декодеров следите за уникальностью имени в рамках файла.
- **Кодировка**: Если логи содержат не-ASCII символы (кириллица, emoji), убедитесь, что `ossec.conf` агента содержит `<syslog_charset>UTF-8</syslog_charset>`.
- **Регистрозависимость**: PCRE2 чувствителен к регистру. Для игнорирования регистра используйте флаг `(?i)` в начале паттерна.
- **Ограничение длины поля**: По умолчанию Wazuh обрезает поля длиннее 256 символов. Для увеличения лимита измените `global.decode_utf8` в `internal_options.conf`.

## Заметки по миграции (4.x → 5.0)

- **XML декодеры**: В Wazuh 5.0 XML-декодеры по-прежнему поддерживаются, но новые возможности (WCS, Content Manager) требуют YAML-формата.
- **Пути**: В 5.0 файлы декодеров больше не реплицируются через кластерный файловый синх. Используйте Content Manager API или единый менеджер для distributing декодеров.
- **Маппинг полей**: При миграции сопоставьте старые имена полей с WCS:
  | 4.x поле | 5.x WCS поле |
  | :--- | :--- |
  | `srcip` | `source.ip` |
  | `dstip` | `destination.ip` |
  | `srcuser` | `user.name` |
  | `action` | `event.action` |
  | `status` | `event.outcome` |
  | `program_name` | `process.name` |
- **Не поддерживаемые XML-паттерны**: `<multiline_regex>`, `<fts>`, некоторые плагины. При миграции проверьте официальную таблицу equivalence.

## Резервное копирование и версионирование

| Компонент | Путь | Важность |
| :--- | :--- | :--- |
| Кастомные декодеры (XML) | `/var/wazuh-manager/etc/decoders/` | Critical |
| Декодеры (YAML/Content Manager) | Экспорт через API в Git | Critical |
| Конфигурации Logcollector | `/var/wazuh-manager/etc/ossec.conf` | High |

```bash
# Бэкап XML-декодеров
tar -czf wazuh-decoders-backup-$(date +%F).tar.gz /var/wazuh-manager/etc/decoders/

# Экспорт YAML-декодеров из Content Manager (пример)
curl -sk -u admin:admin https://localhost:55000/content/decoders -o decoders-backup.json
```

## Рекомендации по PCRE2

- **Регистрозависимость**: В отличие от стандартного OSRegex, PCRE2 чувствителен к регистру. Используйте `(?i)` в начале паттерна для игнорирования регистра.
- **Жадность**: Используйте нежадные квантификаторы `.*?` вместо `.*`, чтобы избежать захвата лишних данных в конце строки.
- **Производительность**: Всегда используйте `<prematch>` перед `<regex>`. Простой поиск подстроки в десятки раз быстрее компиляции и выполнения регулярного выражения.
- **Якоря**: Используйте `^` и `$` для ограничения границ строки, если формат лога детерминирован.
- **Тестирование regex**: Используйте `pcre2test` для отладки сложных выражений перед внесением в декодер:
  ```bash
  echo "User 'admin' logged from '192.168.1.10'" | pcre2test -q '^User '\''(\S+)'\'' logged from '\''(\d+\.\d+\.\d+\.\d+)'\''$'
  ```

## Best Practices

1.  **Приоритет декодера перед правилом**: Никогда не пишите regex-правило для сырого лога, если можно написать декодер. Декодер извлекает поля один раз, правило использует их многократно.
2.  **Минимизация regex**: Избегайте сложных regex с lookahead/lookbehind в высоконагруженных правилах. Используйте `<prematch>` + простой `<regex>`.
3.  **Стандартные имена полей**: Используйте WCS-имена (`source.ip`, `user.name`, `event.action`) для совместимости с Sigma-правилами и Dashboard.
4.  **Атомарность деплоя**: Всегда валидируйте декодеры через `wazuh-logtest` перед перезапуском менеджера. Ошибка в одном XML-файле может привести к отказу запуска.
5.  **Изоляция изменений**: Храните кастомные декодеры в отдельном файле (`local_decoder.xml`), не редактируйте системные файлы `ruleset/`.
6.  **Документация**: Для каждого декодера указывайте `metadata` (в YAML) или комментарии (в XML) с форматом исходного лога и примером.
7.  **Версионирование**: Храните декодеры в Git. Каждый коммит должен содержать описание формата лога и ссылку на приложение/сервис.

## См. также

- [Wazuh: обзор SIEM](../wazuh.md)
- [Правила корреляции и обнаружения в Wazuh](./wazuh-rules.md) — интеграция декодера с правилами.
- [Автоматизация Wazuh через Ansible](./ansible-automation-per-agent.md) — управление Detection as Code.
- [Мониторинг целостности файлов (FIM) в Wazuh](./wazuh-fim.md) — примеры правил для syscheck.
- [Оценка конфигурации безопасности (SCA) в Wazuh](./wazuh-sca.md) — интеграция SCA-событий с правилами.
- [Сбор логов (Logcollector) в Wazuh](./wazuh-log-collection.md) — конфигурация источников для декодирования.
