# Zabbix: Дополнительная информация

## Процесс запуска Zabbix Server

При запуске Zabbix Server выполняет следующую последовательность действий:

1. **Чтение конфигурации** (`zabbix_server.conf`).
2. **Загрузка модулей** и создание кэшей в памяти.
3. **Проверка версии схемы БД**.
4. **Запуск HA менеджера** (в режиме высокой доступности).
5. **Загрузка конфигурации мониторинга из БД** в кэш. В Zabbix 7.0+ это происходит инкрементально, что снижает нагрузку.
6. **Запуск рабочих процессов** (`pollers`, `trappers`, `history syncers` и др.).

---

## Реализация LLD для кастомных метрик

Этот подход обеспечивает максимальную гибкость, позволяя мониторить практически любые динамические сущности.

### 1. Скрипт обнаружения

На хосте создается скрипт, который формирует JSON для LLD. Пример `my_discovery_script.sh`:

```bash
#!/bin/bash
echo '{ "data": [
  { "{#ITEMNAME}": "CPU_Usage", "{#ITEMDESCRIPTION}": "Загрузка процессора" },
  { "{#ITEMNAME}": "Memory_Free", "{#ITEMDESCRIPTION}": "Свободная память" }
] }'
```

### 2. UserParameter для агента

В конфигурации Zabbix-агента (`/etc/zabbix/zabbix_agentd.conf.d/`) создается `UserParameter` для вызова скрипта:

```
UserParameter=otus.discovery,/usr/local/bin/my_discovery_script.sh
```

### 3. LLD-правило в Zabbix

В шаблоне создается правило обнаружения с ключом `otus.discovery`, которое будет выполнять этот `UserParameter` для получения JSON.

### 4. Прототипы элементов

Создаются прототипы элементов данных с типом **`Zabbix trapper`** и ключами, использующими макросы из JSON.

- **Прототип:** `Custom metric {#ITEMDESCRIPTION}` с ключом `custom.metric[{#ITEMNAME}]`.

### 5. Отправка данных

Для отправки значений обнаруженных метрик на Zabbix-сервер используется утилита `zabbix_sender` в отдельном скрипте, запускаемом по расписанию (cron).

---

## Оптимизация и устранение неисправностей

Для обеспечения стабильной работы и высокой производительности Zabbix важно регулярно проводить оптимизацию и уметь диагностировать проблемы.

> Подробное руководство доступно в документе: **[Поиск и устранение неисправностей и тюнинг производительности Zabbix](./zabbix_troubleshooting_and_performance_tuning.md)**.

---

## Версии и поддержка

| Версия | Тип | Дата выхода | Поддержка до |
|--------|-----|-------------|--------------|
| Zabbix 7.0 | LTS | Июнь 2024 | Июнь 2029 |
| Zabbix 7.4 | Stable | Октябрь 2025 | Октябрь 2026 |
| Zabbix 8.0 | LTS (план) | 2026 | — |

---

## Официальные ресурсы

* **[Официальный сайт Zabbix](https://www.zabbix.com/)**
* **[Документация Zabbix 7.0](https://www.zabbix.com/documentation/7.0)**
* **[Репозитории загрузок](https://www.zabbix.com/download_sources)**
* **[Release Notes](https://www.zabbix.com/release_notes)**

---

## Полезные ссылки

| Тема | Документ |
|------|----------|
| Архитектура и компоненты | **[Определения и концепции](./definitions_and_concepts.md)** |
| Мониторинг СУБД | **[Мониторинг Баз Данных с помощью Zabbix](./zabbix_database_monitoring.md)** |
| Мониторинг MySQL | **[Мониторинг MySQL с помощью Zabbix Agent](../Databases/MySQL/monitoring.md)** |
| Мониторинг PostgreSQL | **[Мониторинг PostgreSQL в Zabbix](./zabbix_postgresql_monitoring.md)** |
| Лучшие практики | **[Лучшие практики настройки Zabbix](./zabbix_best_practices.md)** |
| Диагностика и тюнинг | **[Поиск и устранение неисправностей и тюнинг производительности Zabbix](./zabbix_troubleshooting_and_performance_tuning.md)** |
| Стратегии сбора метрик | **[Стратегии сбора метрик](../Concepts/Observability_and_Monitoring/observability_overview.md#стратегии-сбора-метрик)** |
| Интеграция с Grafana | **[Grafana](../Grafana/grafana_overview.md)** |
