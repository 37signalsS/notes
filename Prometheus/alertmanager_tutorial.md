# Практическое руководство по настройке Alertmanager

*Этот туториал основан на конфигурационном файле, описанном в [[./alertmanager_setup.md]].*

Практика выполняется на сервере мониторинга с root-привилегиями.

1.  **Сохраним конфигурационный файл**

    Перед началом настройки, необходимо подтвердить пользовательское соглашение для email, с которого будут отправляться email уведомления. Для этого перейдите по ссылке, авторизуйтесь и подтвердите соглашение. Для авторизации - имя пользователя `<user name>@edu-prom.slurm.io`, а пароль совпадает с паролем ssh.

    Выполним команду для создания правил алертинга. Перед выполнением необходимо поменять: `<email_1>` и `<email_2>` на реальные email (если нет двух разных email, можно указать один), а так же заменить `<user name>`, `<Password>`.

    ```bash
    cat <<EOF > /etc/alertmanager/alertmanager.yml
    global:
      smtp_smarthost: smtp.yandex.ru:465
      smtp_from: '<user name>@edu-prom.slurm.io'
      smtp_auth_username: '<user name>@edu-prom.slurm.io'
      smtp_auth_password: '<Password>'

    route:
      group_by: ['alertname', 'service']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 1h
      receiver: team-monitoring

      routes:
      - match:
          service: prom
        receiver: team-ops
      - match:
          severity: (warnings|error|critical)
        receiver: team-monitoring

    inhibit_rules:
    - source_match:
        severity: 'critical'
        alertname: PrometheusConfigurationReload
      target_match:
        severity: 'critical'

    receivers:
    - name: 'team-ops'
      email_configs:
        - to: '<email_1>'
          send_resolved: true
          require_tls: false
    - name: 'team-monitoring'
      email_configs:
        - to: '<email_2>'
          send_resolved: true
    EOF
    ```
    Данная конфигурация использует группировку по `alertname` и `service`. Все сообщения с label `service: prom` будут отправлены на `email_1`, все алерты c label `severity: critical, error` и `warning` будут отправлены на `email_2`. Если есть алерт c label `service: prom` и `alertname: PrometheusConfigurationReload`, остальные алерты отправляться не будут.

    > **NB!** В реальной жизни routing будет намного сложнее, и для его визуализации можно воспользоваться [сайтом](https://www.prometheus.io/webtools/alerting/routing-tree-editor/).

2.  **Перезагружаем Alertmanager:**
    ```bash
    systemctl reload alertmanager.service
    ```

3.  **Тестирование**

    3.1. **Ломаем конфиг Prometheus**
    Добавьте в начало `/etc/prometheus/prometheus.yml` символ `1` и выполните `systemctl reload prometheus.service`. Это приведет к отправке алерта об ошибке в конфигурации.

    3.2. **Останавливаем node exporter**
    Остановите `node_exporter` на двух серверах:
    ```bash
    systemctl stop node_exporter.service
    ```
    Дождитесь, пока сработает alert rule. В веб-интерфейсе Prometheus (`http://<monitoring_IP>:9090/alerts`) должно быть активно два алерта. При этом новых email приходить не должно, так как работает подавление (`inhibit_rules`).

    3.3. **Исправляем конфигурацию Prometheus**
    Удалите `1` из `/etc/prometheus/prometheus.yml` и выполните `systemctl reload prometheus.service`.
    Теперь должно прийти еще 2 уведомления: одно об исправлении конфигурации Prometheus, второе – о недоступности двух exporters.

---
**Связанные темы:**
*   [[./alertmanager_setup.md]]
*   [[./alerting_rules.md]]
