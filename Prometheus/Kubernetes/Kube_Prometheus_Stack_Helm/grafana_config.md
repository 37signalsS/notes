# Конфигурация Grafana в kube-prometheus-stack

> Для детального изучения Grafana обратитесь к основной заметке: [grafana_overview](../../../Grafana/grafana_overview.md).

> **Установка:** Инструкции по онлайн и оффлайн установке см. в [Практических сценариях](./practical_scenarios.md).

* `grafana.enabled`: `true`
  * **Рекомендация:** Оставить `true`.

* `grafana.adminPassword`:
  * **Описание:** Позволяет задать пароль для пользователя `admin`.
  * **Рекомендация:** Установить надежный пароль или сослаться на `Secret`. Не оставлять пароль по умолчанию.

        ```yaml
        grafana:
          adminPassword: "MySecurePassword"
        ```

* `grafana.grafana.ini`:
  * **Описание:** Позволяет кастомизировать основной конфигурационный файл Grafana `grafana.ini`.
  * **Пример:** Настройка `root_url` важна, чтобы Grafana генерировала корректные ссылки в уведомлениях.

        ```yaml
        grafana:
          grafana.ini:
            server:
              root_url: "https://grafana.example.com"
        ```

* `grafana.sidecar`:
  * **Описание:** Включает механизм автоматического обнаружения и загрузки дашбордов из `ConfigMap`.
  * **Рекомендация:** Обязательно включить для реализации подхода "Dashboards as Code".

        ```yaml
        grafana:
          sidecar:
            dashboards:
              enabled: true
              label: grafana_dashboard
              # Сайдкар будет искать ConfigMap'ы с этим лейблом
        ```

* `grafana.additionalGrafanaPlugins`:
  * **Описание:** Позволяет устанавливать дополнительные плагины для Grafana.
  * **Пример:** Установка плагина `worldmap-panel`.

        ```yaml
        grafana:
          additionalGrafanaPlugins:
            - "grafana-worldmap-panel"
        ```

* `grafana.persistence`:
  * **Описание:** Настройка постоянного хранилища для Grafana.
  * **Рекомендация (Production):** Обязательно включить, чтобы сохранять дашборды, созданные через UI, и другие настройки.

        ```yaml
        persistence:
          enabled: true
          type: pvc
          storageClassName: "your-storage-class"
          accessModes:
            - ReadWriteOnce
          size: 10Gi
        ```
