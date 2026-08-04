# Мониторинг PHP-FPM

## Определения

**PHP-FPM (FastCGI Process Manager)** — это альтернативная реализация PHP FastCGI с дополнительными функциями, предназначенная для высоконагруженных сайтов. Мониторинг PHP-FPM критичен для обеспечения стабильности веб-приложений на базе PHP.

**PHP-FPM Status Page** — встроенная страница статуса, предоставляющая информацию о текущем состоянии пулов процессов, количестве активных соединений и очередях.

---

## Ключевые метрики

### 1. Длина очереди запросов (Listen Queue) — КРИТИЧЕСКАЯ МЕТРИКА
*   **`listen queue`**: Количество запросов, ожидающих освобождения свободного воркера (child process).
*   **Интерпретация**: Если очередь начинает расти, это означает, что PHP-FPM не справляется с входящим потоком. Это более важный показатель, чем просто количество запущенных процессов, так как он напрямую указывает на наличие «бутылочного горлышка».
*   **`listen queue len`**: Максимальный размер очереди. Если `listen queue` достигает этого значения, новые запросы будут отклоняться (502 Gateway Timeout на стороне Nginx).

### 2. Состояние процессов (Processes State)
*   **`active processes`**: Количество воркеров, занятых обработкой запросов в данный момент.
*   **`idle processes`**: Количество свободных воркеров, готовых к работе.
*   **`total processes`**: Общее количество воркеров.
*   **Динамика**: Если `active processes` постоянно равно лимиту (`max_children`), необходимо либо увеличивать лимиты (если позволяют ресурсы CPU/RAM), либо оптимизировать код приложения.

### 3. Потребление памяти
*   Воркеры PHP-FPM могут «течь» по памяти (Memory Leaks) из-за неоптимального кода или расширений.
*   **Решение**: Использование параметра `pm.max_requests` для автоматического перезапуска воркера после обработки определенного количества запросов.

---

## Практические сценарии

### Настройка страницы статуса

1.  **В конфигурации PHP-FPM (например, `www.conf`):**
    ```ini
    pm.status_path = /status
    ```
2.  **В конфигурации Nginx:**
    ```nginx
    location /status {
        allow 127.0.0.1;
        deny all;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_pass unix:/var/run/php/php-fpm.sock;
    }
    ```

### Анализ вывода `/status`

```text
pool:                 www
process manager:      dynamic
start time:           04/Aug/2026:10:00:00 +0300
start since:          3600
accepted conn:        15000
listen queue:         0
max listen queue:     5
listen queue len:     128
idle processes:       8
active processes:     2
total processes:      10
max active processes: 20
max children reached: 0
slow requests:        0
```

*   **`max children reached`**: Если значение > 0, значит пул достигал своего лимита. Это сигнал к пересмотру параметров `pm.max_children`.
*   **`slow requests`**: Количество запросов, превысивших `request_slowlog_timeout`. Требует анализа `slowlog` для поиска медленных функций.

---

## Дополнительная информация

### См. также
*   **[Мониторинг Nginx](../Nginx/Performance/monitoring.md)**
*   **[Тюнинг производительности PHP-FPM](./performance_tuning.md)**
*   **[Логирование и отладка PHP](./logging_and_debugging.md)**
