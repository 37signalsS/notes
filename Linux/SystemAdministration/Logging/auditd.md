# auditd: Аудит событий безопасности

## Определения

**`auditd` (Audit Daemon)** — система отслеживания событий безопасности на уровне ядра (системные вызовы). Протоколирует действия в системе, отвечая на вопросы: **кто, когда, что и с каким объектом сделал**.

**Отличия от других систем логирования:**

| Система | Уровень | Назначение |
| :--- | :--- | :--- |
| `auditd` | Ядро | Аудит системных вызовов, доступ к файлам |
| `journald` | Пользовательское пространство | Логи служб и приложений |
| `rsyslog` | Пользовательское пространство | Фильтрация и пересылка логов |

## Базовые концепции

### Правила аудита (Audit Rules)

Правила определяют отслеживаемые события:

| Тип правила | Описание | Пример |
| :--- | :--- | :--- |
| **Файловый мониторинг** | Отслеживание чтения, записи, изменения атрибутов файлов | `-w /etc/passwd -p wa` |
| **Системные вызовы** | Отслеживание конкретных syscall | `-a exit,always -S open` |
| **События пользователей** | Аутентификация, запуск процессов | `-m USER_LOGIN` |

### Ключи аудита (Audit Keys)

**Ключ** (`-k key_name`) — текстовая метка для группировки событий. Упрощает поиск и фильтрацию в логах.

### Формат правил

```bash
# Синтаксис: -action [параметры]
# Примеры:
-w /path/to/file -p perms -k key_name    # Мониторинг файла
-a exit,always -S syscall -k key_name    # Мониторинг syscall
```

**Параметры прав доступа (`-p`):**

- `r` — чтение
- `w` — запись
- `x` — исполнение
- `a` — изменение атрибутов

## Практические сценарии

### Отслеживание изменений файла

1. **Установить правило:**

   ```bash
   # Отследить изменения /etc/passwd
   sudo auditctl -w /etc/passwd -p wa -k passwd_changes
   ```

2. **Найти события в логе:**

   ```bash
   # Поиск по ключу
   sudo ausearch -k passwd_changes
   
   # Поиск по файлу
   sudo ausearch -f /etc/passwd
   ```

3. **Сгенерировать отчет:**

   ```bash
   # Отчет о событиях аутентификации
   sudo aureport -au
   
   # Отчет по всем событиям
   sudo aureport
   ```

### Мониторинг критических файлов

```bash
# /etc/shadow (пароли)
sudo auditctl -w /etc/shadow -p wa -k shadow_access

# /etc/sudoers (sudo конфигурация)
sudo auditctl -w /etc/sudoers -p wa -k sudoers_changes

# /etc/ssh/sshd_config (SSH конфигурация)
sudo auditctl -w /etc/ssh/sshd_config -p wa -k sshd_config
```

### Отслеживание команд пользователей

```bash
# Все вызовы execve (запуск программ)
sudo auditctl -a exit,always -F arch=b64 -S execve -k exec_tracking

# Команды от конкретного пользователя
sudo auditctl -a exit,always -F uid=1000 -k user_1000_actions
```

### Поиск и анализ событий

```bash
# Поиск по временному диапазону
sudo ausearch -k passwd_changes --start today --end now

# Поиск по PID
sudo ausearch -p 1234

# Поиск неудачных попыток доступа
sudo ausearch -m SYSCALL -sc open -sv failed

# Сводный отчет за день
sudo aureport --summary
```

## Дополнительная информация

### Постоянное хранение правил

Правила `auditctl` сбрасываются после перезагрузки. Для постоянного хранения:

```bash
# Добавить правило в файл
echo "-w /etc/passwd -p wa -k passwd_changes" | sudo tee -a /etc/audit/rules.d/audit.rules

# Перезапустить службу
sudo systemctl restart auditd
```

**Проверка загруженных правил:**

```bash
sudo auditctl -l
```

### Структура логов

- **Лог-файл:** `/var/log/audit/audit.log`
- **Конфигурация демона:** `/etc/audit/auditd.conf`
- **Правила:** `/etc/audit/rules.d/`

### Утилиты auditd

| Утилита | Назначение |
| :--- | :--- |
| `auditctl` | Управление правилами |
| `ausearch` | Поиск событий в логах |
| `aureport` | Генерация отчетов |
| `auditd` | Демон службы |

### Интеграция с другими системами

- **journald:** События auditd могут дублироваться в journal (настраивается в `auditd.conf`)
- **SIEM-системы:** Логи `/var/log/audit/audit.log` отправляются в Splunk, ELK, QRadar

### Ссылки по теме

- **Обзор логирования:** [logging_overview.md](./logging_overview.md)
- **journald:** [journald.md](./journald.md)
- **Анализ сбоев:** [error_and_crash_analysis.md](./error_and_crash_analysis.md)
