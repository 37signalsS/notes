# Runbooks и Incident Response для веб-серверов

**Актуально для:** Nginx 1.24+, Angie 1.4+, HAProxy 2.8+, Alertmanager 0.27+, Linux kernel 5.15+ (systemd 249+)

## Определения

- **Инцидент (Incident)** — неплановое событие, приводящее к деградации качества, снижению доступности или полному отказу сервиса (всплеск кодов 5xx, падение worker-процессов, исчерпание пула дескрипторов, срабатывание OOM Killer, насыщение диска или истечение TLS-сертификатов).
- **Runbook (Операционный плейбук / Инструкция)** — формализованное пошаговое руководство для дежурного инженера (On-call / SRE / Sysadmin) по диагностике, локализации и купированию конкретного известного инцидента.
- **MTTD (Mean Time To Detect)** — среднее время от фактического возникновения аномалии или сбоя до момента фиксации системой мониторинга и срабатывания алерта.
- **MTTA (Mean Time To Acknowledge)** — среднее время от генерации алерта мониторингом до взятия инцидента в работу дежурным инженером.
- **MTTR (Mean Time To Repair / Recover)** — среднее время от обнаружения сбоя до полного восстановления штатной работоспособности сервиса.
- **MTBF (Mean Time Between Failures)** — среднее время наработки на отказ между завершением предыдущего инцидента и возникновением следующего.
- **Severity (SEV / Приоритет критичности)** — шкала градации влияния инцидента на пользователей и бизнес (от SEV1 / P1 — критический простой до SEV4 / P4 — незначительное отклонение).
- **Escalation Path (Путь эскалации)** — регламентированный маршрут и временные пороги передачи управления инцидентом на более высокие уровни экспертизы (L1 → L2 → L3 / Senior SRE → Incident Commander → Руководство).
- **Incident Commander (IC / Командир инцидента)** — лицо, обладающее исключительными полномочиями по координации процесса реагирования, распределению задач, приоритизации гипотез и принятию решений о радикальных мерах купирования (откат, сброс нагрузки, временное отключение подсистем).
- **Scribe (Хранитель хроники)** — участник штаба реагирования, фиксирующий поминутный таймлайн событий, примененные команды, гипотезы и статус систем для последующего разбора.
- **War Room (Координационный штаб)** — выделенный защищенный голосовой или текстовый канал экстренной коммуникации участников ликвидации аварии.
- **Радиус поражения (Blast Radius)** — объем инфраструктуры, клиентского трафика или данных, затрагиваемый возникшим сбоем либо операцией по его устранению.
- **Mitigation (Купирование)** — комплекс экстренных мер, направленных на немедленное восстановление доступности сервиса для пользователей (откат деплоя, изоляция узла, отдача кэша, включение заглушки), выполняемый до выяснения коренной причины.
- **Resolution (Разрешение)** — полное устранение первопричины сбоя в коде, конфигурации или инфраструктуре, гарантирующее невозможность тривиального повторения аварии.
- **Load Shedding (Сброс нагрузки)** — намеренное и контролируемое отсечение избыточного входящего потока запросов на сетевом периметре при исчерпании вычислительной емкости для предотвращения общего коллапса веб-сервера.
- **Blameless Postmortem (Безвиновный постмортем)** — аналитическая процедура и итоговый документ разбора инцидента, исследующие системные уязвимости и несовершенство процессов без возложения персональной вины на инженеров.
- **5 Whys (Метод «5 почему»)** — техника выявления глубинной первопричины сбоя посредством последовательного перехода от внешних симптомов к базовым системным дефектам.
- **Action Items (Корректирующие мероприятия)** — конкретный перечень задач инженерной профилактики по итогам постмортема, привязанных к ответственным лицам и срокам исполнения (SLA).
- **Maintenance Window (Технологическое окно)** — регламентированный интервал времени минимальной пользовательской активности для выполнения плановых рискованных работ на инфраструктуре.
- **Change Freeze (Заморозка изменений)** — административный и технический запрет на внесение изменений в производственную среду в периоды пиковых бизнес-нагрузок или аварийного восстановления.
- **Backout Plan (План отката)** — детерминированный алгоритм возврата сервиса в заведомо стабильное исходное состояние в случае сбоя при проведении регламентных работ или развертывании релиза.

---

## Основные концепции

### Жизненный цикл инцидента (Incident Lifecycle)

Эффективный процесс Incident Response для веб-серверов в SRE-парадигме строится по строгому конвейеру:

```text
 ┌───────────┐      ┌─────────┐      ┌──────────────┐      ┌────────────┐      ┌────────────┐      ┌────────────┐
 │ Detection │ ───► │ Triage  │ ───► │ Mobilization │ ───► │ Mitigation │ ───► │ Resolution │ ───► │ Postmortem │
 └───────────┘      └─────────┘      └──────────────┘      └────────────┘      └────────────┘      └────────────┘
   Prometheus         Класс P1-P4      War Room, IC          Отсечение           Устранение         5 Whys,
   Blackbox,          Оценка потерь    Распределение         симптомов,          первопричины,      Action Items,
   Alertmanager       и Blast Radius   ролей (Scribe)        Failover/Cache      верификация        обновление RB
```

1. **Detection (Обнаружение):** Фиксация аномалии автоматизированным мониторингом (Prometheus Alertmanager, Blackbox Exporter, системные probe-тесты) либо эскалация от техподдержки.
2. **Triage (Сортировка и классификация):** Первичная оценка симптомов, определение затронутых критических путей пользователя (Critical User Journeys), определение класса тяжести (Severity) и установление допустимого окна реагирования.
3. **Mobilization (Мобилизация):** Открытие виртуального War Room, назначение Incident Commander (IC), фиксация Scribe, уведомление стейкхолдеров о старте аварийных работ.
4. **Mitigation (Купирование):** Первоочередная остановка деградации («остановить кровотечение»). Главный приоритет — восстановление доступности трафика для клиентов (переключение на резервные бэкенды, активация кэша `stale-if-error`, откат изменений, отсечение L7-атак), а не поиск глубинных причин.
5. **Resolution (Полное разрешение):** Идентификация дефекта, применение долговременного исправления конфигурации или ПО, подтверждение стабильности метрик и закрытие активной фазы инцидента.
6. **Postmortem (Ретроспектива и профилактика):** Подготовка безвиновного разбора, выявление узких мест архитектуры и постановка задач на доработку Runbook и автоматизации.

---

### Матрица уровней критичности (Severity Matrix) для веб-трафика

Классификация определяет темп реагирования, состав привлекаемых инженеров и протоколы оповещения:

| Класс | Критерии сбоя веб-сервера | MTTA | Цель MTTR | Эскалация и оповещение |
| :--- | :--- | :--- | :--- | :--- |
| **P1 / SEV1 (Critical)** | Полная недоступность шлюза / веб-сервера; ошибки 5xx > 15% от общего трафика; отказ TLS-сертификатов на основном домене; падение всех upstream-нод пула. | $\le 5$ мин | $\le 30$ мин | Incident Commander, Lead SRE, Дежурный администратор, CTO, Product Owner. Синхронизация каждые 15 мин. |
| **P2 / SEV2 (High)** | Частичная деградация: 5xx от 2% до 15%; отказ половины узлов балансировки; задержка обработки (p95 latency) выросла в $\ge 3$ раза от нормы; отказ второстепенных API-эндпоинтов. | $\le 15$ мин | $\le 2$ часа | L2 On-call SRE, Team Lead разработки, дежурный системный администратор. Синхронизация каждые 30 мин. |
| **P3 / SEV3 (Medium)** | Локальные сбои без потери бизнес-функций: деградация метрик отдельного upstream-воркера; периодические одиночные 502/504; исчерпание диска $> 80\%$ (есть запас времени $> 6$ часов). | $\le 1$ час | $\le 8$ часов | L1 / L2 On-call инженер. Обработка в рамках стандартной дежурной смены. |
| **P4 / SEV4 (Low)** | Незначительные отклонения: предупреждения линтера конфигурации; некритичные предупреждения ротации логов; единичные запросы 4xx/5xx от сканеров сети. | $\le 4$ часа | Следующий рабочий день | Плановый тикет в бэклог эксплуатации. |

---

### Анатомия и стандарт структуры производственного Runbook

Каждый операционный Runbook должен храниться как версионируемый код (Runbook as Code) в Markdown и удовлетворять принципу «Executable & Deterministic»: инженер в условиях ночного стресса не должен догадываться о значении параметров.

Обязательные атрибуты Runbook:
1. **Заголовок и метаданные:** Точное имя сбоя, целевой сервис, поддерживаемые версии ПО, критичность (P1–P4).
2. **Симптомы и триггеры:** Список точных имен алертов Prometheus, шаблоны диагностических сообщений в `error.log` и внешние проявления для клиентов.
3. **Предварительные требования (Prerequisites):** Необходимые привилегии (`sudo`), пути к бинарным файлам, расположение конфигураций, порты и используемые инструменты.
4. **Экспресс-диагностика (Triaging):** Детерминированные команды с ожидаемым выводом (`# → результат`), позволяющие за 2 минуты подтвердить или опровергнуть гипотезу.
5. **Пошаговое купирование (Mitigation):** Четкая последовательность команд для немедленного снятия нагрузки или переключения трафика.
6. **Валидация восстановления (Validation):** Проверочные запросы (`curl`), анализ кодов возврата и проверка метрик на дашборде.
7. **План отката (Backout Plan):** Действия по отмене примененных аварийных изменений, если купирование не привело к успеху или ухудшило ситуацию.
8. **Пороги эскалации:** Тайм-аут самостоятельной работы (например, «если через 10 минут статус не восстановился — эскалировать на L3»).

---

### Модель коммуникации и распределение ролей в Incident Command System (ICS)

В ходе ликвидации инцидентов P1/P2 действует принцип единоначалия:
- **Incident Commander (IC):** Не пишет код и не правит конфигурацию руками. Он держит общую картину, ведет таймбокс гипотез (не более 7–10 минут на одну проверку), авторизует рискованные действия и управляет эскалацией.
- **Operations Lead / Investigator:** Непосредственно выполняет диагностику, применяет команды плейбука, формулирует технические наблюдения.
- **Scribe / Communications Lead:** Фиксирует таймлайн в чате инцидента, готовит сводки (SitRep — Situation Report) для руководства и обновляет публичную статусную страницу.

Регламент сводки (SitRep):
```text
[СТАТУС ИНЦИДЕНТА] P1 — Массовые 502 ошибки на шлюзе reverse-proxy
Время с начала: 18 минут
Влияние: 35% запросов к /api/v1/checkout завершаются ошибкой 502
Текущее действие: Применено переключение на резервный upstream-пул, выполняется graceful reload Nginx
Следующий статус-апдейт: через 10 минут (в 14:40 MSK)
```

---

## Практические сценарии и типовые runbooks

### Сценарий 1: Runbook «Массовый каскадный сбой 502 Bad Gateway / 504 Gateway Timeout»

#### 1. Метаданные
- **Severity:** P1 (Critical) / P2 (High)
- **Целевой стек:** Nginx 1.24+, Angie 1.4+, Linux systemd
- **Триггеры мониторинга:** `Alert: HighHttp5xxRate`, `Alert: UpstreamDown`

#### 2. Симптомы
- Всплеск HTTP 502 / 504 на внешних балансировщиках.
- Сообщения в `/var/log/nginx/error.log`:
  - `connect() failed (111: Connection refused) while connecting to upstream`
  - `upstream prematurely closed connection while reading response header from upstream`
  - `1024 worker_connections are not enough while connecting to upstream`

#### 3. Экспресс-диагностика (Triaging)
Выполните последовательно на хосте шлюза:

```bash
# 1. Проверка состояния сокетов и бэкенда (порт 8000)
ss -lntp '( sport = :8000 )'
# → LISTEN 128 127.0.0.1:8000 users:(("gunicorn",pid=4120,fd=5))
# Если строки LISTEN нет — процесс бэкенда упал или не слушает сокет

# 2. Проверка очереди переполнения сокета ядра (Send-Q > Recv-Q указывает на блокировку бэкенда)
ss -lnt '( sport = :8000 )'
# → State  Recv-Q Send-Q Local Address:Port
# → LISTEN 129    128    127.0.0.1:8000

# 3. Прямой тестовый запрос к бэкенду в обход Nginx
curl -Iv --connect-timeout 2 --max-time 5 http://127.0.0.1:8000/health
# → HTTP/1.1 200 OK (или Connection refused / таймаут)

# 4. Проверка системного статуса юнита upstream-приложения
systemctl status myapp.service --no-pager -l
# → Active: failed (Result: exit-code) или Active: activating (auto-restart)
```

#### 4. Пошаговое купирование (Mitigation)

**Шаг 4.1: Активация аварийной отдачи устаревшего кэша (Stale Cache) и статического Fallback**
Если бэкенды перегружены или аварийно завершаются, предотвратите показ технической ошибки пользователям через кэширующий контур:

```nginx
# Вставка директив в блок location /etc/nginx/conf.d/upstream_proxy.conf
location / {
    proxy_pass http://backend_cluster;
    proxy_connect_timeout 2s;
    proxy_read_timeout 5s;
    proxy_send_timeout 3s;

    # Использование устаревшего кэша при отказе бэкенда
    proxy_cache app_cache;
    proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
    proxy_cache_background_update on;
    proxy_cache_lock on;

    # Аварийный перехват ошибок шлюза
    proxy_intercept_errors on;
    error_page 502 503 504 = @fallback_maintenance;
}

location @fallback_maintenance {
    root /var/www/static_pages;
    rewrite ^(.*)$ /maintenance.html break;
    add_header Retry-After "30" always;
}
```

Примените изменения без разрыва соединений:
```bash
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

sudo systemctl reload nginx
# → Процесс перезагружен без обрыва текущих TCP-сессий
```

**Шаг 4.2: Экстренное переключение на резервный контур (Backup Peer)**
В блоке `upstream` активируйте резервные ноды или резервный кластер:

```nginx
# /etc/nginx/conf.d/backends.conf
upstream backend_cluster {
    zone backend_zone 1m;
    server 10.0.10.11:8000 max_fails=3 fail_timeout=10s;
    server 10.0.10.12:8000 max_fails=3 fail_timeout=10s;
    # Резервный хост для холодного переключения трафика
    server 10.0.20.15:8000 backup;
}
```

**Шаг 4.3: Перезапуск и дренаж зависшего сервиса приложения через systemd**
```bash
# Graceful перезапуск упавшего бэкенда с таймаутом
sudo systemctl restart myapp.service

# Контроль появления сокета
timeout 15 bash -c 'until ss -lnt | grep -q ":8000"; do sleep 1; done'
# → Завершается успешно, когда сокет открыт
```

#### 5. Валидация восстановления
```bash
# Проверка ответа через шлюз Nginx
curl -Iv -H "Host: example.com" http://127.0.0.1/
# → HTTP/1.1 200 OK

# Контроль частоты кодов 502 в реальном времени
tail -n 100 /var/log/nginx/access.log | awk '{print $9}' | sort | uniq -c
# → 98 200
# →  2 502
```

#### 6. План отката (Backout Plan)
Если аварийная конфигурация нарушила маршрутизацию:
```bash
# Возврат исходной конфигурации из Git репозитория сервера
cd /etc/nginx && sudo git checkout HEAD -- conf.d/
sudo nginx -t && sudo systemctl reload nginx
```

---

### Сценарий 2: Runbook «Критическое исчерпание памяти и аварийное завершение процессов OOM Killer»

#### 1. Метаданные
- **Severity:** P1 (Critical)
- **Целевой стек:** Linux Kernel 5.x/6.x, systemd, Nginx / Angie / HAProxy
- **Триггеры мониторинга:** `Alert: HostOOMKillDetected`, `Alert: HostMemoryUnderPressure`

#### 2. Симптомы
- Веб-сервер перестает отвечать, запросы обрываются по таймауту.
- В `journalctl -k` или `dmesg` сообщения вида:
  `Out of memory: Killed process 24512 (nginx) total-vm:845120kB, anon-rss:512400kB`

#### 3. Экспресс-диагностика (Triaging)
```bash
# 1. Поиск недавних событий ликвидации процессов ядром Linux
sudo dmesg -T | grep -E -i 'oom[-_]killer|killed process' | tail -n 5
# → [Thu Oct 15 08:30:12 2026] Out of memory: Kill process 3841 (nginx) score 450 or sacrifice child

# 2. Анализ текущего распределения оперативной памяти и Swap
free -h
# →               total        used        free      shared  buff/cache   available
# → Mem:           31Gi        29Gi       350Mi       1.2Gi       1.8Gi       850Mi
# → Swap:         4.0Gi       3.9Gi       100Mi

# 3. Топ-10 процессов по потреблению резидентной памяти (RSS)
ps -eo pid,ppid,user,%mem,rss,comm --sort=-rss | head -n 11
# →   PID  PPID USER     %MEM   RSS   COMMAND
# → 12040     1 myapp    68.4 21845120 python3
# →  3840     1 root      1.2  390000 nginx
```

#### 4. Пошаговое купирование (Mitigation)

**Шаг 4.1: Защита веб-сервера от OOM Killer через systemd OOMScoreAdjust**
Веб-сервер (Nginx / HAProxy) не должен уничтожаться ядром первым при нехватке памяти, вызванной бэкендом. Установите наивысший приоритет выживания:

```bash
# Создание override конфигурации для systemd юнита nginx
sudo systemctl edit nginx.service
```

Внесите параметры:
```ini
[Service]
# -1000 полностью запрещает ядру убивать мастер-процесс Nginx при OOM
OOMScoreAdjust=-1000
```

Примените изменения:
```bash
sudo systemctl daemon-reload
sudo systemctl restart nginx.service

# Проверка установленного score
cat /proc/$(cat /run/nginx.pid)/oom_score_adj
# → -1000
```

**Шаг 4.2: Ограничение пула worker-процессов для снижения давления на RAM**
Если Nginx был запущен с `worker_processes auto;` на 64-ядерном сервере, каждый воркер удерживает буферы. В условиях дефицита памяти сократите число воркеров:

```bash
# Временная фиксация числа воркеров
sudo sed -i 's/worker_processes auto;/worker_processes 4;/' /etc/nginx/nginx.conf
sudo nginx -t && sudo systemctl reload nginx
```

**Шаг 4.3: Установка жестких cgroup-лимитов для сервиса бэкенда**
Предотвратите разрастание утечки памяти в сервисе бэкенда:
```bash
sudo systemctl set-property myapp.service MemoryMax=16G MemoryHigh=14G
# → Лимит вступает в силу немедленно через cgroups v2
```

**Шаг 4.4: Экстренное освобождение дисковых кэшей страниц Linux**
```bash
# Сброс clean pages из pagecache (безопасно для данных)
sync
echo 1 | sudo tee /proc/sys/vm/drop_caches
# → Освобождает буферы ядра, увеличивая доступную память
```

#### 5. Валидация восстановления
```bash
free -h
# → Доступная память (available) должна вырасти выше 20% от общего объема
systemctl status nginx --no-pager
# → Active: active (running)
```

#### 6. План отката (Backout Plan)
После устранения утечки памяти в бэкенде верните конфигурацию Nginx:
```bash
sudo sed -i 's/worker_processes 4;/worker_processes auto;/' /etc/nginx/nginx.conf
sudo nginx -t && sudo systemctl reload nginx
```

---

### Сценарий 3: Runbook «Кризис TLS/SSL-сертификатов: истечение срока или повреждение цепочки»

#### 1. Метаданные
- **Severity:** P1 (Critical)
- **Целевой стек:** Nginx, OpenSSL 3.x, Linux PKI
- **Триггеры мониторинга:** `Alert: SSLCertExpiringSoon`, `Alert: BlackboxTlsHandshakeFailed`

#### 2. Симптомы
- Клиенты видят браузерное предупреждение `SEC_ERROR_EXPIRED_CERTIFICATE` или `NET::ERR_CERT_COMMON_NAME_INVALID`.
- Логи Nginx: `SSL_do_handshake() failed (SSL: error:0A000086:SSL routines::certificate verify failed)`.

#### 3. Экспресс-диагностика (Triaging)
```bash
# 1. Проверка срока действия локального сертификата на диске
openssl x509 -in /etc/ssl/certs/example.com.crt -noout -dates -issuer -subject
# → notBefore=Oct 10 00:00:00 2025 GMT
# → notAfter=Oct 14 23:59:59 2026 GMT
# → issuer=C = US, O = Let's Encrypt, CN = R3
# → subject=CN = example.com

# 2. Проверка сертификата, отдаваемого сервером по сети (проверка кэша воркеров)
echo | openssl s_client -servername example.com -connect 127.0.0.1:443 2>/dev/null | openssl x509 -noout -dates
# → notAfter=Oct 14 23:59:59 2026 GMT (срок истек)

# 3. Валидация соответствия закрытого ключа и сертификата (хэши должны совпасть)
CERT_MOD=$(openssl x509 -noout -modulus -in /etc/ssl/certs/example.com.crt | openssl md5)
KEY_MOD=$(openssl rsa -noout -modulus -in /etc/ssl/private/example.com.key | openssl md5)
[ "$CERT_MOD" = "$KEY_MOD" ] && echo "MATCH" || echo "MISMATCH ERROR"
# → MATCH
```

#### 4. Пошаговое купирование (Mitigation)

**Шаг 4.1: Аварийный перевыпуск сертификата через Certbot (Webroot режим)**
Если ACME-клиент не сработал автоматически, выполните принудительный выпуск:

```bash
# Ручной запуск перевыпуска с явным указанием webroot каталога
sudo certbot certonly --webroot -w /var/www/letsencrypt \
    -d example.com -d www.example.com \
    --force-renewal --non-interactive --agree-tos -m admin@example.com
# → Successfully received certificate.
# → Certificate is saved at: /etc/letsencrypt/live/example.com/fullchain.pem
```

**Шаг 4.2: Подключение аварийного Wildcard / Резервного сертификата**
Если выпуск Let's Encrypt заблокирован из-за rate limits (превышение лимита запросов), временно подключите резервный корпоративный сертификат:

```bash
# Создание симлинков на резервную связку
sudo ln -sf /etc/ssl/backup_certs/star_example_com.crt /etc/ssl/certs/example.com.crt
sudo ln -sf /etc/ssl/backup_certs/star_example_com.key /etc/ssl/private/example.com.key

# Проверка синтаксиса и перезагрузка
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
sudo systemctl reload nginx
```

**Шаг 4.3: Сборка полной цепочки (Fullchain)**
Частая ошибка — указание листового сертификата без промежуточного УЦ (Intermediate CA), что вызывает сбои у клиентов на мобильных ОС:
```bash
# Объединение листового сертификата и промежуточных сертификатов УЦ
cat /etc/ssl/certs/leaf.crt /etc/ssl/certs/intermediate.crt > /etc/ssl/certs/example.com.fullchain.crt

# Обновление директивы в Nginx
# ssl_certificate /etc/ssl/certs/example.com.fullchain.crt;
sudo nginx -t && sudo systemctl reload nginx
```

#### 5. Валидация восстановления
```bash
# Проверка рукопожатия и цепочки через OpenSSL
echo | openssl s_client -servername example.com -connect 127.0.0.1:443 -verify_return_error 2>&1 | grep -E 'Verify return code|notAfter'
# → Verify return code: 0 (ok)
# → notAfter=Jan 13 12:00:00 2027 GMT
```

#### 6. План отката (Backout Plan)
```bash
# Возврат предыдущих симлинков при несовпадении ключа
sudo ln -sf /etc/ssl/certs/example.com.crt.bak /etc/ssl/certs/example.com.crt
sudo ln -sf /etc/ssl/private/example.com.key.bak /etc/ssl/private/example.com.key
sudo systemctl reload nginx
```

---

### Сценарий 4: Runbook «Аварийное переполнение диска логами и буферами (No space left on device)»

#### 1. Метаданные
- **Severity:** P2 (High)
- **Целевой стек:** Linux filesystem (ext4/xfs), Nginx, systemd-journald
- **Триггеры мониторинга:** `Alert: DiskSpaceUnder10Percent`, `Alert: InodesExhausted`

#### 2. Симптомы
- Запросы возвращают `500 Internal Server Error`.
- Ошибки в `/var/log/nginx/error.log`:
  `open() "/var/lib/nginx/tmp/client_body/0000001234" failed (28: No space left on device)`
  `write() to "/var/log/nginx/access.log" failed (28: No space left on device)`

#### 3. Экспресс-диагностика (Triaging)
```bash
# 1. Проверка занятого дискового пространства и inode по разделам
df -h /var/log /var/lib/nginx /tmp
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda2        50G   50G     0 100% /var

df -i /var
# → Filesystem       Inodes   IUsed   IFree IUse% Mounted on
# → /dev/sda2       3276800 3276800       0  100% /var (если исчерпаны inode)

# 2. Поиск скрытых файлов, удаленных командой rm, но удерживаемых процессами (дескрипторная утечка)
sudo lsof +L1 /var
# → COMMAND   PID  USER   FD   TYPE DEVICE   SIZE/OFF NLINK  NAME
# → nginx    4122 nginx    4w   REG    8,2 2489128912     0 /var/log/nginx/access.log (deleted)
```

#### 4. Пошаговое купирование (Mitigation)

**Шаг 4.1: Безопасное усечение открытых логов без разрыва дескрипторов**
Удаление через `rm` файла, открытого процессом Nginx, **не освобождает** место на диске до перезапуска процесса. Применяйте `truncate`:

```bash
# Обнуление удаленного, но удерживаемого дескриптора через procfs
TARGET_PID=4122
TARGET_FD=4
sudo cp /dev/null /proc/$TARGET_PID/fd/$TARGET_FD
# Место освобождается ядром немедленно

# Безопасное обнуление активных логов
sudo truncate -s 0 /var/log/nginx/access.log
sudo truncate -s 0 /var/log/nginx/error.log
```

**Шаг 4.2: Ротация и переоткрытие логов по сигналу USR1**
Сообщите воркерам веб-сервера о необходимости переоткрыть файлы логов:
```bash
# Ротация логов без рестарта Nginx
sudo kill -USR1 $(cat /run/nginx.pid)
# Или через CLI
sudo nginx -s reopen
```

**Шаг 4.3: Экстренная очистка дискового кэша прокси и буферов**
```bash
# Очистка старых временных буферов тел запросов старше 1 дня
sudo find /var/lib/nginx/tmp/ -type f -mmin +60 -delete

# Очистка зоны proxy_cache (удаление элементов кэша с сохранением дерева каталогов)
sudo find /var/cache/nginx/proxy_cache/ -mindepth 1 -maxdepth 3 -type f -delete
```

**Шаг 4.4: Очистка системного журнала journald**
```bash
# Ограничение размера системного журнала последними 2 днями
sudo journalctl --vacuum-time=2d
# Или ограничение по размеру
sudo journalctl --vacuum-size=500M
```

#### 5. Валидация восстановления
```bash
df -h /var
# → Использование диска должно снизиться до величины < 80%

# Тест записи со стороны Nginx
sudo -u nginx touch /var/log/nginx/test_write && sudo rm -f /var/log/nginx/test_write
# → Завершается без ошибок
```

#### 6. План отката (Backout Plan)
Если в результате очистки были удалены структуры каталогов:
```bash
sudo mkdir -p /var/lib/nginx/tmp/{client_body,proxy,fastcgi}
sudo chown -R nginx:nginx /var/lib/nginx/tmp/
sudo chmod 700 /var/lib/nginx/tmp/*
sudo systemctl reload nginx
```

---

### Сценарий 5: Runbook «L7 HTTP-Flood / Аномальный всплеск трафика (Worker Saturation)»

#### 1. Метаданные
- **Severity:** P1 (Critical) / P2 (High)
- **Целевой стек:** Nginx 1.24+, Angie, Linux netfilter (iptables / ipset)
- **Триггеры мониторинга:** `Alert: HighHttpTrafficAnomaly`, `Alert: NginxWorkerSaturation`

#### 2. Симптомы
- Резкий рост активных соединений, `nginx_connections_active` достигает `worker_processes * worker_connections`.
- Всплеск клиентских обрывов (код 499) и таймаутов (код 504).
- Высокая утилизация CPU процессами `nginx: worker process` в режиме `sys` (system calls).

#### 3. Экспресс-диагностика (Triaging)
```bash
# 1. Выявление топ-15 IP-адресов по количеству запросов в access.log за последние 3 минуты
tail -n 10000 /var/log/nginx/access.log | awk '{print $1}' | sort | uniq -c | sort -nr | head -n 15
# → 4512 198.51.100.42
# → 3890 203.0.113.19
# →   45 192.168.1.10

# 2. Анализ наиболее атакуемого URI и User-Agent
tail -n 10000 /var/log/nginx/access.log | awk -F\" '{print $2}' | sort | uniq -c | sort -nr | head -n 5
# → 7500 POST /api/v1/login HTTP/1.1
```

#### 4. Пошаговое купирование (Mitigation)

**Шаг 4.1: Блокировка атакующих адресов на уровне ядра через ipset / iptables**
Блокировка на уровне веб-сервера все равно тратит сокеты и память на TCP-рукопожатие. Фильтрация на уровне ядра сбрасывает пакеты до входа в user-space:

```bash
# Создание ipset таблицы для атакующих адресов
sudo ipset create blacklist hash:ip hashsize 4096 maxelem 100000 -exist

# Добавление правила в iptables (если еще не добавлено)
sudo iptables -I INPUT -m set --match-set blacklist src -j DROP

# Экстренное добавление выявленных адресов в ipset
sudo ipset add blacklist 198.51.100.42
sudo ipset add blacklist 203.0.113.19
# → Пакеты с указанных IP сбрасываются ядром на L4
```

**Шаг 4.2: Включение экстренного L7 Rate Limiting в Nginx**
Ограничьте частоту обращений к атакуемому эндпоинту:

```nginx
# /etc/nginx/conf.d/emergency_ratelimit.conf
# Зона ограничения запросов по IP-адресу (10 Мб память = ~160 000 адресов)
limit_req_zone $binary_remote_addr zone=attack_protect:10m rate=5r/s;
limit_conn_zone $binary_remote_addr zone=conn_protect:10m;

server {
    # Сброс зависших соединений атакующих клиентов
    reset_timedout_connection on;
    client_body_timeout 5s;
    client_header_timeout 5s;

    location /api/v1/login {
        # Жесткое ограничение с возвратом 429 Too Many Requests
        limit_req zone=attack_protect burst=10 nodelay;
        limit_req_status 429;
        limit_conn conn_protect 5;
        limit_conn_status 429;

        proxy_pass http://backend_cluster;
    }
}
```

Примените изменения:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

**Шаг 4.3: Блокировка вредоносного User-Agent на L7**
```nginx
# В блоке server
if ($http_user_agent ~* (SemrushBot|AhrefsBot|python-requests|curl|Go-http-client)) {
    return 403;
}
```

#### 5. Валидация восстановления
```bash
# Проверка снижения активных соединений Nginx
curl -s http://127.0.0.1/nginx_status
# → Active connections: 142
# → server accepts handled requests
# →  142 142 1890

# Проверка счетчиков сброшенных пакетов в iptables
sudo iptables -L INPUT -v -n | grep blacklist
# →  52000  28M DROP all -- * * 0.0.0.0/0 0.0.0.0/0 match-set blacklist src
```

#### 6. План отката (Backout Plan)
После прекращения атаки:
```bash
# Очистка таблицы ipset
sudo ipset flush blacklist

# Отключение аварийного конфига
sudo rm -f /etc/nginx/conf.d/emergency_ratelimit.conf
sudo nginx -t && sudo systemctl reload nginx
```

---

### Сценарий 6: Продакшен-конфигурация Prometheus Alertmanager

Для предотвращения «шторма уведомлений» (Alert Fatigue) во время масштабных аварий инфраструктура мониторинга должна использовать точные аннотации со ссылкой на Runbook, правила группировки и правила подавления (Inhibition).

#### 1. Правила алертов Prometheus (`/etc/prometheus/rules/webservers.yml`)

```yaml
groups:
  - name: webserver_incident_rules
    rules:
      # Алерт P1: Полный отказ сервиса Nginx
      - alert: NginxServiceDown
        expr: up{job="nginx_exporter"} == 0
        for: 1m
        labels:
          severity: p1
          domain: webservers
        annotations:
          summary: "Веб-сервер Nginx недоступен на {{ $labels.instance }}"
          description: "Nginx exporter не может собрать метрики. Процесс Nginx остановлен или заблокирован."
          runbook_url: "file:///c:/Users/Elise/notes/WebServers/Concepts/runbooks_incident_response.md#сценарий-2-runbook-критическое-исчерпание-памяти-и-аварийное-завершение-процессов-oom-killer"

      # Алерт P1: Критический уровень ошибок 5xx
      - alert: HighHttp5xxRate
        expr: (sum(rate(nginx_http_requests_total{status=~"5.."}[2m])) by (instance) 
               / sum(rate(nginx_http_requests_total[2m])) by (instance)) * 100 > 15
        for: 2m
        labels:
          severity: p1
          domain: webservers
        annotations:
          summary: "Критическая доля 5xx ошибок (>15%) на {{ $labels.instance }}"
          description: "Текущий процент 5xx ошибок составляет {{ $value | printf \"%.2f\" }}% за последние 2 минуты."
          runbook_url: "file:///c:/Users/Elise/notes/WebServers/Concepts/runbooks_incident_response.md#сценарий-1-runbook-массовый-каскадный-сбой-502-bad-gateway--504-gateway-timeout"

      # Алерт P2: Исчерпание свободного места на диске логов
      - alert: DiskSpaceUnder10Percent
        expr: (node_filesystem_avail_bytes{mountpoint="/var"} / node_filesystem_size_bytes{mountpoint="/var"}) * 100 < 10
        for: 5m
        labels:
          severity: p2
          domain: storage
        annotations:
          summary: "Осталось менее 10% дискового пространства в /var на {{ $labels.instance }}"
          description: "Текущий свободный объем: {{ $value | printf \"%.2f\" }}%. Риск аварийной остановки записи логов."
          runbook_url: "file:///c:/Users/Elise/notes/WebServers/Concepts/runbooks_incident_response.md#сценарий-4-runbook-аварийное-переполнение-диска-логами-и-буферами-no-space-left-on-device"
```

#### 2. Конфигурация маршрутизации Alertmanager (`/etc/alertmanager/alertmanager.yml`)

```yaml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'cluster', 'domain']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default_webhook'

  routes:
    # Маршрут критических P1 инцидентов (немедленная нотификация)
    - match:
        severity: p1
      receiver: 'pager_duty_oncall'
      group_wait: 10s
      repeat_interval: 30m

    # Маршрут P2 инцидентов
    - match:
        severity: p2
      receiver: 'team_chat_ops'
      repeat_interval: 2h

# Правило подавления (Inhibition): если хост полностью упал (NodeDown),
# не рассылать алерты о падении Nginx, диска или upstream на этой же ноде
inhibit_rules:
  - source_match:
      alertname: 'HostDown'
    target_match:
      domain: 'webservers'
    equal: ['instance']

receivers:
  - name: 'default_webhook'
    webhook_configs:
      - url: 'http://127.0.0.1:9095/events'

  - name: 'pager_duty_oncall'
    webhook_configs:
      - url: 'http://127.0.0.1:9095/p1_alerts'
        send_resolved: true

  - name: 'team_chat_ops'
    webhook_configs:
      - url: 'http://127.0.0.1:9095/ops_chat'
        send_resolved: true
```

#### 3. Управление сайленсами через CLI `amtool`
Во время локализации сбоя дежурный инженер должен заглушить шумные алерты:

```bash
# Добавление сайленса на 1 час для конкретного хоста во время проведения работ
amtool silence add instance="web-node-01.infra:9100" \
    --duration=1h \
    --comment="Купирование инцидента с диском по Runbook #4 (Ticket OPS-4102)" \
    --author="oncall_sre"
# → Silence ID: 4f1a8b2c-3d4e-5f6a-7b8c-9d0e1f2a3b4c

# Просмотр активных сайленсов
amtool silence query
# → ID: 4f1a8b2c...  Active  Author: oncall_sre  Comment: Купирование инцидента...

# Досрочное снятие сайленса после восстановления системы
amtool silence expire 4f1a8b2c-3d4e-5f6a-7b8c-9d0e1f2a3b4c
# → Expired silence 4f1a8b2c-3d4e-5f6a-7b8c-9d0e1f2a3b4c
```

---

### Сценарий 7: Шаблон производственного Blameless Postmortem

Ниже представлен заполненный пример реального разбора сбоя веб-сервера.

```markdown
# Postmortem: Каскадный сбой 502 Bad Gateway в кластере Ingress (2026-10-15)

## 1. Паспорт инцидента
- **Дата и время:** 2026-10-15 08:15 — 08:42 MSK (длительность: 27 минут).
- **Критичность:** P1 (Critical).
- **Incident Commander:** @alex_sre.
- **Operations Lead:** @dmitry_devops.
- **Scribe:** @elena_sysadmin.
- **Влияние на бизнес (Impact):** 28 500 запросов завершились ошибкой 502; просадка доступности SLO сервиса Checkout составила 0.04% за месяц; прямой финансовый ущерб: ~150 брошенных корзин.

## 2. Поминутный таймлайн (Timeline)
- **08:15** — Завершен плановый релиз сервиса платежного шлюза (версия v2.4.1).
- **08:17** — `Alertmanager fired: HighHttp5xxRate (42% ошибок на ingress-01)`.
- **08:18** — Дежурный инженер подтвердил алерт (MTTA = 1 мин), открыт War Room инцидента.
- **08:21** — Назначен Incident Commander. Локализован источник ошибок: бэкенды `auth-service` возвращают RST при установке TCP-соединения.
- **08:25** — Проведена экспресс-проверка `ss -lnt`: бэкенд перешел в состояние OOMKilled из-за некорректного размера пула потоков.
- **08:28** — Применен Runbook #1: включена аварийная отдача устаревшего кэша (`stale-if-error`) и перенаправление на резервный контур (backup upstream).
- **08:33** — Ошибки 502 снизились до 0.5% (купирование успешно, MTTR mitigation = 16 минут).
- **08:37** — Выполнен откат релиза платежного шлюза до версии v2.4.0 через systemd.
- **08:42** — Все бэкенды стабильны, трафик переведен в штатный режим, инцидент закрыт.

## 3. Анализ первопричин методом «5 Почему» (Root Cause Analysis / 5 Whys)
1. **Почему возникли ошибки 502 на балансировщике?**
   → Бэкенды `auth-service` мгновенно сбрасывали TCP-соединения (`Connection refused`).
2. **Почему бэкенды сбрасывали соединения?**
   → Процессы сервиса были аварийно завершены OOM-киллером операционной системы.
3. **Почему сработал OOM Killer?**
   → Потребление памяти процессом превысило лимит cgroups (4 Гб) за 90 секунд.
4. **Почему сервис потребил столько памяти?**
   → В релизе v2.4.1 пул worker-потоков был увеличен с 16 до 256 без изменения базового лимита буфера ответов.
5. **Почему такое изменение прошло на Production без проверки?**
   → В конфигурационном шаблоне Ansible отсутствовала валидация соотношения `threads_count * buffer_size <= cgroup_memory_limit`.

## 4. Что сработало хорошо
- Алерт Prometheus сработал через 2 минуты после деградации.
- Runbook #1 содержал точные директивы `proxy_cache_use_stale`, что позволило быстро восстановить обслуживание 99% пользователей до починки кода.
- Координация в War Room позволила избежать хаотичных перезапусков серверов.

## 5. Где возникли сложности
- В логах Nginx отсутствовал заголовок с IP-адресом конкретного сбойного upstream-пира (использовался стандартный формат `combined` вместо кастомного с `$upstream_addr`).
- Первая попытка перезапуска бэкенда заняла 4 минуты из-за отсутствия директивы `TimeoutSec=10` в systemd-юните.

## 6. Корректирующие мероприятия (Action Items)
| Действие | Тип | Ответственный | Срок (SLA) | Статус |
| :--- | :--- | :--- | :--- | :--- |
| Добавить `$upstream_addr` и `$upstream_response_time` в формат access_log Nginx | Detect | @dmitry_devops | 3 дня | В работе |
| Добавить линтер параметров пула потоков в CI-пайплайн проверки конфигураций | Prevent | @alex_sre | 7 дней | Запланировано |
| Настроить `TimeoutStopSec=10s` в systemd-юните `auth-service` | Mitigate | @elena_sysadmin | 2 дня | Выполнено |
| Провести GameDay учения по сценарию массового падения бэкендов | Process | @alex_sre | 14 дней | Запланировано |
```

---

## Операции и команды

Справочная таблица экстренных команд администратора при ликвидации аварий веб-серверов:

| Направление | Команда | Назначение и ожидаемый результат |
| :--- | :--- | :--- |
| **Сигналы Nginx** | `sudo nginx -t` | Проверка синтаксиса перед перезагрузкой (`# → syntax is ok`). |
| **Сигналы Nginx** | `sudo systemctl reload nginx` | Безопасная перечитка конфигурации по сигналу `SIGHUP` без потери соединений. |
| **Сигналы Nginx** | `sudo kill -USR1 $(cat /run/nginx.pid)` | Переоткрытие файлов логов без остановки воркеров (после ротации/truncate). |
| **Сигналы Nginx** | `sudo kill -QUIT $(cat /run/nginx.pid)` | Graceful остановка: завершение обработки активных запросов перед выходом. |
| **Сокеты Linux** | `ss -lntp '( sport = :80 or sport = :443 )'` | Проверка прослушивания внешних портов веб-сервером и идентификаторов PID. |
| **Сокеты Linux** | `ss -s` | Сводная статистика сокетов ядра (проверка переполнения `TIME-WAIT` / `ESTAB`). |
| **Сетевой стек** | `netstat -s \| grep -E 'listen queue'` | Проверка переполнения очереди `backlog` сокетов (drops/overflows ядра). |
| **Файлы и память** | `sudo truncate -s 0 /var/log/nginx/*.log` | Экстренное обнуление логов на переполненном диске без удаления дескрипторов. |
| **Файлы и память** | `sudo lsof +L1 /var` | Поиск удаленных (`deleted`), но не освобожденных дескрипторов файлов. |
| **Сетевой фильтр** | `sudo ipset add blacklist <IP> -exist` | Мгновенная блокировка атакующего IP-адреса на уровне ядра Linux. |
| **Сетевой фильтр** | `sudo iptables -I INPUT -p tcp --dport 80 -m connlimit --connlimit-above 50 -j REJECT` | Экстренное ограничение числа одновременных TCP-сессий с одного IP. |
| **Alertmanager** | `amtool alert --query='alertname="HighHttp5xxRate"'` | Быстрый просмотр активных алертов с терминала администратора. |
| **Alertmanager** | `amtool silence add alertname="HighHttp5xxRate" --duration=30m -c "Mitigation"` | Экстренное подавление шума на время восстановительных работ. |

---

## Диагностика и решение проблем процесса реагирования

### 1. Дребезг алертов (Flapping Alerts) и ложные вызовы On-call
- **Симптом:** Алерт переходит в статус `FIRING` на 30 секунд, будит дежурного инженера и тут же переходит в `RESOLVED`, повторяясь многократно за ночь.
- **Причина:** Отсутствие временного окна стабилизации (`for`) в правиле Prometheus или использование мгновенного значения `rate()` на слишком коротком интервале.
- **Решение:**
  - Установите порог стабилизации `for: 5m` для метрик ресурсов и `for: 2m` для кодов 5xx.
  - Окно вычисления скорости (`rate([интервал])`) должно быть как минимум в 4 раза больше интервала сбора метрик (`scrape_interval`). При `scrape_interval: 15s` минимальное окно — `[1m]`.

### 2. Усталость от алертов (Alert Fatigue)
- **Симптом:** Инженеры игнорируют уведомления в аварийном чате или массово заглушают канал.
- **Причина:** Мониторинг настроен на внутренние технические шумы («загрузка CPU > 80%»), которые не влияют на доступность сервиса для пользователей.
- **Решение:**
  - Принцип **Actionable Alerts**: каждый P1/P2 алерт обязан требовать конкретного действия человека. Если при срабатывании алерта инженер ничего не должен предпринимать руками — алерт удаляется либо переводится в категорию P4 (тикет в бэклог).
  - Привязка к пользовательскому опыту (User-Centric SLI): алерты настраиваются на просадку успешности запросов и задержки (RED method: Rate, Errors, Duration), а не на абстрактные проценты утилизации.

### 3. Аналитический паралич (Analysis Paralysis) в горячей фазе
- **Симптом:** Дежурные инженеры тратят 40 минут на изучение дампов памяти и стектрейсов упавшего бэкенда, пока 100% пользователей видят ошибку 502.
- **Причина:** Нарушение разделения между этапами **Mitigation** (купирование) и **Resolution** (исправление).
- **Решение:**
  - Строгое правило Incident Commander: *«Сначала восстанови трафик, потом ищи причину»*.
  - Если причина не очевидна за 5 минут — применяется детерминированный откат (Rollback), снятие ноды с балансировки или включение аварийной статической заглушки. Глубокий дебаг переносится в тестовую среду.

### 4. Сбои при откате (Failed Rollback)
- **Симптом:** Команда выполняет откат версии сервиса на предыдущую, но сервер падает с ошибкой несовместимости схемы базы данных или структуры конфигурации.
- **Причина:** Нарушение принципа обратной совместимости (Backward Compatibility) при изменении схемы данных и отсутствие предварительно верифицированного плана отката (Backout Plan).
- **Решение:**
  - Правило двухфазных миграций: изменения базы данных всегда должны поддерживать как новую, так и предыдущую версию кода приложения.
  - Наличие проверенного скрипта отката конфигурации веб-сервера (`git checkout HEAD~1 -- conf.d/`).

### 5. Обрыв цепочки эскалации (Broken On-Call Escalation)
- **Симптом:** Инцидент P1 не решается в течение 30 минут, потому что дежурный инженер не ответил на пейджер, а автоматическая эскалация не сработала.
- **Причина:** Отсутствие вторичной (secondary/backup) очереди дежурства и жестких тайм-аутов подтверждения (Ack Timeout).
- **Решение:**
  - Настройка автоматического перехода алерта на Backup On-call при отсутствии Ack через 5 минут.
  - При отсутствии ответа через 15 минут — автоматический звонок на уровень Team Lead / Head of Infrastructure.

---

## Лучшие практики

1. **Принцип «One Alert — One Runbook»:**
   Ни одно правило алертинга критичности P1 или P2 не допускается к внедрению на production-мониторинге без ссылки на верифицированный Runbook в поле `annotations.runbook_url`.
2. **Runbook as Code в Git:**
   Все инструкции должны храниться в Markdown рядом с кодом сервиса или в централизованной базе знаний, проходить регулярный code review и обновляться после каждого постмортема.
3. **Безопасные манипуляции с процессами:**
   Никогда не выполняйте `systemctl restart nginx` на продакшене без крайней необходимости. Всегда используйте `nginx -t && systemctl reload nginx` (SIGHUP). Перезапуск обрывает активные TCP-сессии и сбрасывает кэш SSL-сессий.
4. **Безопасная работа с файловой системой:**
   Никогда не удаляйте активные файлы логов через `rm` при нехватке места. Используйте `truncate -s 0 /path/to/log` и последующий сигнал `USR1` (`nginx -s reopen`).
5. **Автоматизация Backout Plan:**
   Перед внесением любого изменения в конфигурацию веб-сервера фиксируйте контрольную точку (Git commit или бэкап файла `cp config.conf config.conf.bak`).
6. **Регулярные учения (GameDays / Chaos Drills):**
   Раз в квартал проводите учебные аварии на staging-окружении: имитация падения upstream, исчерпания памяти или истечения TLS-сертификатов для проверки скорости реакции команды по Runbook.
7. **Жесткий контроль выполнения Action Items:**
   Задачи, зафиксированные в Blameless Postmortem для предотвращения повторения P1-инцидентов, должны браться в спринт с наивысшим приоритетом и SLA реализации не более 14 календарных дней.

---

## Дополнительная информация

- **[Диагностика веб-серверов (Troubleshooting)](./webserver_troubleshooting.md)** — универсальные системные алгоритмы поиска неисправностей.
- **[Диагностика и устранение неисправностей Nginx](../Nginx/Operations/nginx_troubleshooting.md)** — углубленный анализ работы master/worker процессов и директив Nginx.
- **[Circuit Breaker и Degradation Patterns](./web_performance/circuit_breaker_and_degradation.md)** — архитектурные шаблоны сброса нагрузки, кэширования `stale-if-error` и защиты от каскадных сбоев.
- **[Zero Downtime Deployment](./web_performance/zero_downtime_deployment.md)** — безопасное обновление бэкендов без генерации ошибок 502/504.
- **[Логирование веб-серверов](./webserver_logging.md)** — настройка структурированных форматов логов и безопасной ротации через logrotate.
- **[Наблюдаемость HTTP-сервисов](../../Networking/Protocols/HTTP/http_monitoring_observability.md)** — реализация RED-метода и мониторинг метрик задержки.
- **[Коды состояния HTTP](../../Networking/Protocols/HTTP/http_status_codes.md)** — детальный справочник причин возврата кодов 4xx и 5xx.
- **[Prometheus Alertmanager](../../Prometheus/alertmanager.md)** — архитектура конвейера обработки алертов, кластеризация и управление через CLI `amtool`.
- **[Prometheus Recording Rules](../../Prometheus/concepts/recording_rules.md)** — вычисление SLO и агрегированных метрик для превентивных алертов.
- **[Управление инцидентами и постмортемы (SRE)](../../CI-CD/Core_Concepts/incident_response_sre.md)** — регламенты координации инцидентов и метрики DORA.
- **[Концепции SRE: надежность, метрики и бюджет ошибок](../../Concepts/sre_concepts_main.md)** — теоретические основы SLI, SLO, SLA и управления бюджетом ошибок.
