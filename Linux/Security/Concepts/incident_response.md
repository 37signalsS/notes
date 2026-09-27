# Реагирование на инциденты (Incident Response) в Linux

## Определения

**Incident Response (Реагирование на инциденты)** — процесс обнаружения, анализа, смягчения и восстановления после нарушений безопасности в информационных системах. Для Linux-систем это включает компрометацию хостов, контейнеров, сетевые атаки, утечки данных и неправомерный доступ.

**Ключевые понятия:**
- **Indicators of Compromise (IoC)** — артефакты, указывающие на компрометацию (подозрительные процессы, файлы, сетевые соединения)
- **Forensics (Форензика)** — сбор и анализ доказательств для восстановления цепочки событий
- **Containment (Сдерживание)** — изоляция скомпрометированных систем для предотвращения распространения
- **Eradication (Устранение)** — удаление вредоносного кода и закрытие векторов атаки

## Теоретический блок

### Фазы реагирования на инциденты

| Фаза | Описание | Ключевые действия |
| :--- | :--- | :--- |
| **1. Подготовка** | Создание процедур, инструментов, обучение команды | Чек-листы, инструменты сбора данных, контакты |
| **2. Обнаружение** | Выявление подозрительной активности | Мониторинг, алерты, логи, аномалии |
| **3. Анализ** | Определение типа и масштаба инцидента | Сбор данных, классификация, оценка влияния |
| **4. Сдерживание** | Изоляция скомпрометированных систем | Отключение от сети, блокировка аккаунтов |
| **5. Устранение** | Удаление угрозы и закрытие векторов атаки | Очистка, патчинг, ротация ключей |
| **6. Восстановление** | Возврат систем в рабочее состояние | Проверка целостности, мониторинг |
| **7. Уроки** | Анализ инцидента и улучшение процедур | Постмортем, обновление документации |

### Типичные векторы атак Linux

| Вектор | Индикаторы | Инструменты обнаружения |
| :--- | :--- | :--- |
| **Брутфорс SSH** | Массовые неудачные входы в логах | `fail2ban`, `auditd`, Wazuh |
| **Эскалация привилегий** | SUID-файлы, capabilities, ядерные уязвимости | `LinPEAS`, `linux-exploit-suggester` |
| **Удержание доступа** | Cron-задачи, systemd-сервисы, SSH-ключи | `chkrootkit`, `rkhunter`, AIDE |
| **Криптомайнеры** | Высокая нагрузка CPU, подозрительные процессы | `htop`, `ps`, `netstat` |
| **Руткиты** | Скрытые процессы, модифицированные бинарники | `rkhunter`, `chkrootkit`, `ausyscall` |
| **Сетевые аномалии** | Необычные соединения, DNS-запросы | `tcpdump`, `ss`, `iftop` |

### Приоритеты реагирования

1. **Критические системы**: базы данных, контроллеры доменов, промежуточное ПО
2. **Данные**: персональные данные, коммерческая тайна, ключи/сертификаты
3. **Доступность**: время простоя, влияние на бизнес
4. **Репутация**: утечка данных, публичность инцидента

## Практический блок

### Чек-лист начального анализа

```bash
# 1. Быстрая оценка системы
uptime                    # Простой системы
last -20                  # Последние входы
w                         # Текущие пользователи
ps auxf                   # Дерево процессов
top -bn1 | head -20       # Топ процессов по CPU/памяти

# 2. Сетевые соединения
ss -tulnp                 # Слушающие порты
ss -anp                   # Активные соединения
netstat -i                # Сетевые интерфейсы
ip route                  # Таблица маршрутизации

# 3. Подозрительные файлы
find / -mtime -1 -type f 2>/dev/null | head -50  # Измененные за 24ч
find / -ctime -1 -type f 2>/dev/null | head -50  # Метаданные изменены за 24ч
find /tmp -type f -executable 2>/dev/null        # Исполняемые в /tmp
find /dev/shm -type f 2>/dev/null                # Файлы в shared memory

# 4. Проверка аудита
sudo ausearch -m avc --start recent              # SELinux нарушения
sudo ausearch -k sshd --start recent             # SSH события
sudo journalctl -u sshd --since "1 hour ago"     # Логи SSH

# 5. Проверка целостности
rpm -Va 2>/dev/null | head -20                   # RPM верификация
debsums -s 2>/dev/null | head -20                # DEB верификация
```

### Сбор данных для форензики

```bash
# Создание образа памяти (требует загрузочной среды)
sudo dd if=/dev/mem of=/evidence/mem.dump bs=1M

# Сбор логов
sudo tar -czf /evidence/logs-$(date +%F).tar.gz \
    /var/log/auth.log \
    /var/log/secure \
    /var/log/syslog \
    /var/log/messages \
    /var/log/audit/audit.log \
    /var/log/journal/

# Сбор информации о системе
sudo systemctl list-units --type=service --state=running > /evidence/services.txt
sudo crontab -l > /evidence/crontab-root.txt
for user in $(cut -f1 -d: /etc/passwd); do
    sudo crontab -u $user -l 2>/dev/null >> /evidence/crontab-all.txt
done

# Сбор сетевой информации
sudo ip addr > /evidence/ip-addr.txt
sudo ip route > /evidence/ip-route.txt
sudo ss -anp > /evidence/ss-anp.txt
sudo iptables -L -n -v > /evidence/iptables.txt

# Сбор процессов
sudo ps auxwwf > /evidence/ps-aux.txt
sudo ps -eo pid,ppid,uid,gid,cmd > /evidence/ps-full.txt
```

### Изоляция скомпрометированной системы

```bash
# 1. Блокировка сетевого доступа (без отключения)
sudo iptables -I INPUT -j DROP
sudo iptables -I INPUT -s 127.0.0.1 -j ACCEPT  # Оставить localhost
sudo iptables -I INPUT -s <trusted_ip> -j ACCEPT  # Доверенный IP

# 2. Блокировка подозрительных пользователей
sudo usermod -L <username>  # Блокировка пароля
sudo chsh -s /usr/sbin/nologin <username>  # Запрет входа

# 3. Остановка подозрительных сервисов
sudo systemctl stop <suspicious_service>
sudo systemctl disable <suspicious_service>

# 4. Изоляция через network namespace (для контейнеров)
sudo ip netns add isolated
sudo ip link set <interface> netns isolated
```

### Анализ подозрительных процессов

```bash
# Проверка процесса
pid=<PID>
cat /proc/$pid/status | grep -E '^(Uid|Gid|Name|PPid)'
cat /proc/$pid/cmdline | tr '\0' ' '
ls -la /proc/$pid/exe
ls -la /proc/$pid/fd/
cat /proc/$pid/maps | head -20

# Проверка сетевых соединений процесса
ss -anp | grep $pid
cat /proc/$pid/net/tcp

# Проверка файлов, открытых процессом
lsof -p $pid

# Проверка modus operandi
strings /proc/$pid/maps | grep -E 'http|https|\.onion'
```

### Реагирование на криптомайнеры

```bash
# 1. Обнаружение
ps aux | sort -nrk 3 | head -10  # Топ по CPU
top -bn1 | grep -E 'miner|xmrig|cryptonight'

# 2. Проверка сетевых соединений
ss -anp | grep -E ':3333|:4444|:5555|:7777|:8888|:9999'  # Типичные порты майнеров

# 3. Проверка cron
for user in $(cut -f1 -d: /etc/passwd); do
    echo "=== $user ==="
    sudo crontab -u $user -l 2>/dev/null
done
ls -la /etc/cron.*/ 
ls -la /var/spool/cron/

# 4. Проверка systemd
systemctl list-units --type=service | grep -v sys
ls -la /etc/systemd/system/
```

### Реагирование на руткиты

```bash
# 1. Проверка скрытых процессов
ps aux | wc -l
ls /proc | grep -E '^[0-9]+$' | wc -l
# Разница указывает на скрытые процессы

# 2. Проверка скрытых модулей ядра
lsmod | grep -v Module
sudo dmesg | grep -i "module"

# 3. Проверка измененных бинарников
rpm -Va | grep -E '^..5'  # Измененные файлы
debsums -s 2>/dev/null | grep FAILED

# 4. Использование специализированных инструментов
sudo chkrootkit
sudo rkhunter --check
sudo lynis audit system
```

### Шаблоны плейбуков

#### Плейбук: Брутфорс SSH

```
Триггер: Алерт fail2ban > 5 банов за 10 минут ИЛИ > 100 Failed password в логах

1. ОБНАРУЖЕНИЕ
   -.lastb | wc -l                          # Количество неудачных входов
   - journalctl -u sshd --since "1 hour ago" | grep "Failed password" | \
     awk '{print $11}' | sort | uniq -c | sort -rn | head  # Топ IP

2. СДЕРЖАНИЕ
   - fail2ban-client status sshd             # Текущие баны
   - fail2ban-client set sshd banip <IP>     # Ручной бан атакующего IP
   - iptables -I INPUT -s <ATTACKER_IP> -j DROP  # Экстренная блокировка

3. АНАЛИЗ
   - ausearch -k sshd --start recent        # События аудита
   - zgrep "Failed password" /var/log/auth.log*  # История атаки
   - Проверить: не было ли успешных входов с атакующих IP

4. УСТРАНЕНИЕ
   - Если были успешные входы → Плейбук "Компрометация аккаунта"
   - Добавить IP в permanent blacklist
   - Рассмотреть.setPasswordAuthentication no в sshd_config

5. ВОССТАНОВЛЕНИЕ
   - Мониторинг 24ч после блокировки
   - Обновление fail2ban/filters если атака через обход
```

#### Плейбук: Компрометация аккаунта (Account Takeover)

```
Триггер: Подозрительная активность от легитимного аккаунта
(вход в нерабочее время, необычные команды, доступ к чувствительным данным)

1. СДЕРЖАНИЕ (немедленно)
   - usermod -L <username>                   # Блокировка пароля
   - chsh -s /usr/sbin/nologin <username>    # Запрет входа
   - kill -9 $(pgrep -u <username>)          # Остановка процессов
   - iptables -I INPUT -s <source_ip> -j DROP  # Блокировка IP (если известен)

2. СБОР ДОКАЗАТЕЛЕЙ
   - last -50 <username>                     # История входов
   - lastb -50 <username>                    # Неудачные попытки
   - ps auxf | grep <username>               # Текущие процессы
   - ls -la /home/<username>/.ssh/           # SSH-ключи
   - cat /home/<username>/.bash_history      # История команд
   - find / -user <username> -mtime -1 2>/dev/null  # Изменённые файлы

3. АНАЛИЗ
   - Проверка cron-задач: crontab -u <username> -l
   - Проверка sudoers: grep <username> /etc/sudoers /etc/sudoers.d/*
   - Проверка authorized_keys: cat /home/<username>/.ssh/authorized_keys
   - Проверка systemd: find /etc/systemd/system -user <username>
   - Сетевые соединения: ss -anp | grep <uid>

4. УСТРАНЕНИЕ
   - Ротация всех паролей аккаунта
   - Удаление SSH-ключей: rm /home/<username>/.ssh/authorized_keys
   - Проверка других аккаунтов с похожими симптомами
   - Проверка LD_PRELOAD, /etc/ld.so.preload

5. ВОССТАНОВЛЕНИЕ
   - Новый пароль + MFA (если не было)
   - usermod -U <username> + chsh -s /bin/bash
   - Мониторинг 72ч
```

#### Плейбук: Руткит/Латеральное движение

```
Триггер: Подозрительные скрытые процессы, изменённые бинарники,
необычные сетевые соединения от root

1. ИЗОЛЯЦИЯ (немедленно)
   - iptables -I INPUT -j DROP
   - iptables -I INPUT -s 127.0.0.1 -j ACCEPT
   - ip netns add isolated && ip link set eth0 netns isolated

2. СБОР ДОКАЗАТЕЛЕЙ (BEFORE remediation)
   - ps auxwwf > /tmp/evidence/ps.txt
   - ss -anp > /tmp/evidence/ss.txt
   - cat /proc/*/environ 2>/dev/null > /tmp/evidence/environ.txt
   - lsmod > /tmp/evidence/lsmod.txt
   - find / -mtime -3 -type f 2>/dev/null > /tmp/evidence/modified.txt
   - rpm -Va 2>/dev/null > /tmp/evidence/rpm_verify.txt

3. ДИАГНОСТИКА
   - # Скрытые процессы
   - ps aux | wc -l && ls /proc | grep -E '^[0-9]+$' | wc -l
   - # Скрытые модули
   - lsmod | grep -v Module
   - # Изменённые бинарники
   - rpm -Va | grep -E '^..5' | head -20
   - # LD_PRELOAD
   - cat /etc/ld.so.preload
   - grep -r "LD_PRELOAD" /proc/*/environ 2>/dev/null

4. УСТРАНЕНИЕ
   - chkrootkit && rkhunter --check
   - Lynis audit system
   - Если найден rootkit → ПЕРЕУСТАНОВКА ОС (не очистка)
   - Ротация ВСХЕ ключей (SSH, API, credentials)

5. ВОССТАНОВЛЕНИЕ
   - Перезагрузка с чистого LiveCD
   - Восстановление из бэкапа
   - Полная ротация credentials
```

#### Плейбук: Криптомайнер

```
Триггер: Аномальное потребление CPU > 90% без видимых процессов в htop

1. ОБНАРУЖЕНИЕ
   - top -bn1 | head -20                    # Топ процессов
   - ps aux | sort -nrk 3 | head -10        # Топ по CPU
   - ss -anp | grep -E ':3333|:4444|:5555|:7777|:8888|:9999'

2. АНАЛИЗ
   - cat /proc/<PID>/exe                    # Путь к бинарнику
   - ls -la /proc/<PID>/exe                 # Симлинк (часто удалён)
   - strings /proc/<PID>/maps | grep -E 'http|\.onion'
   - crontab -l && for u in $(cut -f1 -d: /etc/passwd); do crontab -u $u -l 2>/dev/null; done
   - systemctl list-units --type=service | grep -v sys

3. УСТРАНЕНИЕ
   - kill -9 <PID>
   - rm <бинарник>
   - Очистка cron: crontab -r && rm /var/spool/cron/crontabs/*
   - Очистка systemd: rm /etc/systemd/system/<service>.service

4. ВОССТАНОВЛЕНИЕ
   - Проверка не было ли других векторов (SSH-ключи, sudoers)
   - Мониторинг CPU 24ч
```

### Шаблон коммуникации при инциденте

#### Уведомление команды (внутреннее)

```
[SEVERITY: P1/P2/P3] Incident: <тип>

Affected systems: <список серверов/IP>
Time detected: <UTC время>
Current status: Investigating / Contained / Resolved

Impact: <описание влияния на сервис>
Actions taken: <что уже сделано>
Next steps: <следующие шаги>
ETA for resolution: <ориентировочное время>
Incident lead: <имя/контакт>
```

#### Уведомление руководства (для eskalации)

```
Краткое описание: <1-2 предложения>
Влияние на бизнес: <SLA, пользователи, данные>
Текущий статус: <что сделано>
План действий: <шаги>
Сроки: <когда ожидаем решение>
Ресурсы: <нужна ли помощь>
```

### Шаблон постмортема (Post-Incident Review)

```
## Post-Incident Review: <Название инцидента>

### Метрики
- Time to detect (TTD): <время от начала до обнаружения>
- Time to contain (TTC): <время от обнаружения до сдерживания>
- Time to resolve (TTR): <время от начала до полного устранения>
- Влияние: <количество затронутых пользователей/сервисов>

### Хронология
| Время (UTC) | Событие |
| :--- | :--- |
| HH:MM | Обнаружение аномалии |
| HH:MM | Начало расследования |
| HH:MM | Сдерживание |
| HH:MM | Устранение |
| HH:MM | Восстановление |

### Корневая причина (Root Cause)
<описание>

### Что сработало well
- <список>

### Что нужно улучшить
- <список>

### Action Items
| Действие | Ответственный | Срок |
| :--- | :--- | :--- |
| <действие> | <имя> | <дата> |
```

## Дополнительная информация

### Инструменты для реагирования

| Инструмент | Назначение | Установка |
| :--- | :--- | :--- |
| **LinPEAS** | Автоматизированный аудит безопасности | `curl -L https://github.com/peass-ng/PEASS-ng/releases/latest/download/linpeas.sh | sh` |
| **linux-exploit-suggester** | Поиск уязвимостей для эскалации привилегий | `curl -L https://github.com/The-Z-Labs/linux-exploit-suggester/raw/master/linux-exploit-suggester.sh` |
| **chkrootkit** | Обнаружение руткитов | `sudo apt install chkrootkit` |
| **rkhunter** | Обнаружение руткитов и бэкдоров | `sudo apt install rkhunter` |
| **lynis** | Аудит безопасности системы | `sudo apt install lynis` |
| **ausyscall** | Маппинг системных вызовов аудита | `sudo apt install auditd` |

### Стандарты и регуляторные требования

- **NIST SP 800-61** — Руководство по реагированию на инциденты
- **ISO 27035** — Управление инцидентами безопасности информации
- **PCI DSS** — Требование 12.10: План реагирования на инциденты
- **GDPR** — Требование уведомления об инцидентах в течение 72 часов

### Лучшие практики

1. **Регулярные тренировки**: проводите tabletop exercises каждые 3-6 месяцев
2. **Документация**: ведите чек-листы и процедуры для каждого типа инцидента
3. **Автоматизация**: используйте скрипты для сбора данных и изоляции
4. **Коммуникация**: определите каналы связи для инцидентов (Slack, Telegram, email)
5. **Резервное копирование**: регулярно проверяйте восстановление из бэкапов
6. **Мониторинг**: настройте алерты на критические события безопасности

### Связанные темы
- **[auditd](../../Linux/SystemAdministration/Logging/auditd.md)** — аудит системных вызовов для обнаружения инцидентов
- **[AIDE/Tripwire](./file-integrity-checking.md)** — проверка целостности файлов
- **[SELinux/AppArmor](../Mechanisms/SELinux.md)**, **[AppArmor](../Mechanisms/AppArmor.md)** — принудительный контроль доступа
- **[Сетевой мониторинг](../../Networking/Concepts/firewall_concepts.md)** — обнаружение аномалий в трафике
- **[Централизованное логирование](../../Linux/SystemAdministration/Logging/rsyslog.md)** — сбор логов для анализа
- **[Wazuh](../../Security/Tools/wazuh.md)** — SIEM для корреляции событий
- **[Lynis](../../Security/Tools/lynis.md)** — аудит безопасности после инцидента
- **[Управление секретами](../../Vault/overview.md)** — ротация скомпрометированных секретов
