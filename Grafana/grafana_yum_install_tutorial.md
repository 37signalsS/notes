# Установка Grafana (YUM)

В отличие от Prometheus, у grafana есть репозитарий для большинства современных ОС.

1.  **Добавляем репозитарий с grafana:**

    ```
    [grafana]
    name=grafana
    baseurl=https://rpm.grafana.com
    repo_gpgcheck=1
    enabled=1
    gpgcheck=1
    gpgkey=https://rpm.grafana.com/gpg.key
    sslverify=1
    sslcacert=/etc/pki/tls/certs/ca-bundle.crt
    ```

2.  **Устанавливаем Grafana:**

    ```bash
    yum update -y
    yum install -y grafana
    ```

3.  **Запускаем Grafana:**

    ```bash
    systemctl daemon-reload
    systemctl start grafana-server
    systemctl enable grafana-server.service
    ```

4.  **Проверяем работу.**

    По умолчанию, grafana слушает порт 3000:
    ```bash
    curl -IL http://localhost:3000/login
    ```

    Ответ должен быть примерно таким:

    ```
    HTTP/1.1 200 OK
    Cache-Control: no-cache
    Content-Type: text/html; charset=UTF-8
    Expires: -1
    Pragma: no-cache
    X-Frame-Options: deny
    Date: Mon, 18 Nov 2019 10:46:02 GMT
    ```
