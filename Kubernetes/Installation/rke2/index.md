# RKE2 (Rancher Kubernetes Engine 2)

## Определения

**RKE2 (Rancher Kubernetes Engine 2)** — следующий generation дистрибутив Kubernetes от Rancher Labs, предназначенный для production-кластеров. Использует containerd как среду выполнения по умолчанию и включает встроенные меры безопасности CIS.

**rke2** — утилита командной строки для управления сервисом RKE2 (запуск, остановка, проверка статуса).

**kubectl** — официальный клиент Kubernetes, поставляемый вместе с RKE2 в директории /var/lib/rancher/rke2/bin.

**ctr** — утилита командной строки для взаимодействия с containerd, также поставляемая с RKE2.

## Основные концепции

RKE2 разработан как безопасный по умолчанию дистрибутив Kubernetes. Он устраняет зависимость от Docker, используя containerd, и включает следующие особенности:
- Встроенная поддержка CIS-жесткости
- Автоматическое создание TLS-сертификатов
- Управление кластером через системные сервисы (systemd)
- Встроенные инструменты мониторинга и аудита

## Практическое scénarios

### Настроить и запустить rke2-server

Декларативный конфиг сервера и запуск unit; добавь tls-san чтобы хост LB попал в сертификат API

```bash
printf 'token: <id>\ntls-san:\n  - <host>\n' > /etc/rancher/rke2/config.yaml && systemctl enable --now rke2-server
```

### Использовать встроенные kubectl и ctr

rke2 несёт свои kubectl/crictl/ctr в /var/lib/rancher/rke2/bin, по умолчанию не в $PATH

```bash
export PATH=$PATH:/var/lib/rancher/rke2/bin KUBECONFIG=/etc/rancher/rke2/rke2.yaml && rke2 ctr images ls
```

## Лучшие практики

* Всегда настраивайте tls-san для балансировщиков нагрузки, чтобы сертификат API-сервера был válido для всех точек доступа.
* После установки RKE2 проверьте статус сервиса: `systemctl status rke2-server`
* Для отладки используйте встроенные инструменты: `rke2 kubectl` и `rke2 ctr`
* Храните файл конфигурации /etc/rancher/rke2/config.yaml под контролем версий
* Регулярно обновляйте RKE2, следуя официальной документации

## Дополнительная информация

* Официальная документация: https://docs.rke2.io/
* Источник чест-листа: https://cheatsheet.antonnovikov.com/ru/rke2/