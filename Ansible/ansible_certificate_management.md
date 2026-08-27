# Certificate Automation: Let's Encrypt, Internal CA, Rotation

## Определения

- **Let's Encrypt** — бесплатный центр сертификации, автоматизирующий выдачу и обновление TLS-сертификатов через ACME-протокол
- **ACME (Automatic Certificate Management Environment)** — протокол автоматизации взаимодействия с CA (RFC 8555)
- **Internal CA** — внутренний центр сертификации организации, выдающий сертификаты для приватных сервисов (dogtag, step-ca,Vault PKI)
- **Certificate rotation** — процесс замены сертификата до истечения срока действия с минимальным простоем
- **OCSP Stapling** — механизм проверки статуса отзыва сертификата на стороне сервера, снижающий задержку TLS handshake
- **Certificate chain** — иерархия сертификатов: корневой CA → промежуточный CA → серверный сертификат

---

## Почему это критично

SSL/TLS упоминается в 98 совпадениях по Ansible, но нет standalone-паттерна: "certbot через Ansible + автоматическое обновление через cron + rotation при compromise". Это core-задача для любого SRE.

---

## Сценарий 1: Let's Encrypt через Certbot

### Установка и первичная выдача

```yaml
---
- name: Let's Encrypt setup
  hosts: web_servers
  become: true
  vars:
    certbot_email: "ops@example.com"
    certbot_domains:
      - "app.example.com"
      - "www.example.com"
    certbot_staging: false  # true для тестирования (rate limits)
  tasks:
    - name: Install certbot and nginx plugin
      ansible.builtin.apt:
        name:
          - certbot
          - python3-certbot-nginx
        state: present
        update_cache: true

    - name: Obtain certificate
      ansible.builtin.command:
        cmd: >
          certbot certonly --nginx
          --non-interactive
          --agree-tos
          --email {{ certbot_email }}
          {% for domain in certbot_domains %}
          -d {{ domain }}
          {% endfor %}
          {% if certbot_staging %}
          --staging
          {% endif %}
        creates: /etc/letsencrypt/live/{{ certbot_domains[0 }}/fullchain.pem
      register: certbot_result

    - name: Reload nginx after certificate issuance
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
      when: certbot_result is changed
```

### Автоматическое обновление через systemd timer

```yaml
---
- name: Certbot auto-renewal
  hosts: web_servers
  become: true
  tasks:
    - name: Enable certbot.timer
      ansible.builtin.systemd:
        name: certbot.timer
        enabled: true
        state: started

    - name: Verify renewal timer is active
      ansible.builtin.command:
        cmd: systemctl list-timers certbot.timer --no-pager
      register: timer_check
      changed_when: false

    - name: Show timer status
      ansible.builtin.debug:
        var: timer_check.stdout_lines
```

### Автоматическое обновление через cron (fallback)

```yaml
---
- name: Certbot cron renewal
  hosts: web_servers
  become: true
  tasks:
    - name: Add certbot renewal cron job
      ansible.builtin.cron:
        name: "Certbot auto-renewal"
        minute: "30"
        hour: "2,14"  # Два раза в день
        job: >
          certbot renew --quiet
          --deploy-hook "systemctl reload nginx"
          --post-hook "systemctl reload haproxy"
        user: root

    - name: Add renewal check and logging
      ansible.builtin.cron:
        name: "Certbot renewal log"
        minute: "0"
        hour: "3"
        job: >
          certbot renew --dry-run
          --log-dir /var/log/certbot
          >> /var/log/certbot/renewal-check.log 2>&1
```

### Nginx конфигурация с SSL

```yaml
---
- name: Nginx SSL configuration
  hosts: web_servers
  become: true
  vars:
    cert_domain: "app.example.com"
  tasks:
    - name: Deploy nginx SSL config
      ansible.builtin.template:
        src: templates/nginx_ssl.conf.j2
        dest: /etc/nginx/sites-available/{{ cert_domain }}.conf
        mode: "0644"
      notify: Reload nginx

  handlers:
    - name: Reload nginx
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
```

```jinja2
# templates/nginx_ssl.conf.j2
server {
    listen 443 ssl http2;
    server_name {{ cert_domain }};

    ssl_certificate /etc/letsencrypt/live/{{ cert_domain }}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{{ cert_domain }}/privkey.pem;

    # Mozilla SSL Configuration Generator - Intermediate
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/letsencrypt/live/{{ cert_domain }}/chain.pem;
    resolver 8.8.8.8 8.8.4.4 valid=300s;
    resolver_timeout 5s;

    # HSTS
    add_header Strict-Transport-Security "max-age=63072000" always;
}

server {
    listen 80;
    server_name {{ cert_domain }};
    return 301 https://$host$request_uri;
}
```

---

## Сценарий 2: Internal CA через step-ca / Vault PKI

### Vault PKI — генерация серверных сертификатов

```yaml
---
- name: Internal CA certificate issuance
  hosts: app_servers
  become: true
  vars:
    vault_addr: "https://vault.internal:8200"
    vault_token: "{{ vault_pki_token }}"
    pki_role: "web-server"
    cert_ttl: "720h"  # 30 дней
  tasks:
    - name: Generate certificate from Vault PKI
      ansible.builtin.uri:
        url: "{{ vault_addr }}/v1/pki/issue/{{ pki_role }}"
        method: POST
        headers:
          X-Vault-Token: "{{ vault_token }}"
        body_format: json
        body:
          common_name: "{{ ansible_fqdn }}"
          alt_names: "{{ ansible_fqdn }},{{ ansible_hostname }}"
          ttl: "{{ cert_ttl }}"
        status_code: 200
      register: vault_cert

    - name: Install certificate
      ansible.builtin.copy:
        content: "{{ vault_cert.json.data.certificate }}"
        dest: /etc/ssl/certs/{{ ansible_fqdn }}.pem
        mode: "0644"

    - name: Install private key
      ansible.builtin.copy:
        content: "{{ vault_cert.json.data.private_key }}"
        dest: /etc/ssl/private/{{ ansible_fqdn }}.key
        mode: "0600"

    - name: Install CA chain
      ansible.builtin.copy:
        content: "{{ vault_cert.json.data.issuing_ca }}"
        dest: /etc/ssl/certs/internal-ca.pem
        mode: "0644"

    - name: Reload web server
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
```

### step-ca — автономный internal CA

```yaml
---
- name: step-ca certificate management
  hosts: all
  become: true
  vars:
    step_ca_url: "https://ca.internal:9000"
    step_fingerprint: "abc123..."
    step_provisioner: "admin"
    step_password: "{{ vault_step_ca_pass }}"
  tasks:
    - name: Install step CLI
      ansible.builtin.apt:
        deb: "https://dl.smallstep.com/gh-release/cli/docs-cli-install/v0.27.5/step-cli_0.27.5_amd64.deb"
        state: present

    - name: Bootstrap step CLI
      ansible.builtin.command:
        cmd: "step ca bootstrap --ca-url {{ step_ca_url }} --fingerprint {{ step_fingerprint }}"
        creates: ~/.step/config/defaults.json

    - name: Issue certificate
      ansible.builtin.command:
        cmd: >
          step ca certificate
          "{{ ansible_fqdn }}"
          "/etc/ssl/certs/{{ ansible_fqdn }}.crt"
          "/etc/ssl/private/{{ ansible_fqdn }}.key"
          --ca-url {{ step_ca_url }}
          --root /etc/ssl/certs/internal-ca.crt
          --provisioner {{ step_provisioner }}
          --password-file /tmp/step-pass
          --not-after 720h
        creates: "/etc/ssl/certs/{{ ansible_fqdn }}.crt"
      register: step_cert

    - name: Set certificate permissions
      ansible.builtin.file:
        path: "{{ item.path }}"
        owner: root
        group: root
        mode: "{{ item.mode }}"
      loop:
        - { path: "/etc/ssl/certs/{{ ansible_fqdn }}.crt", mode: "0644" }
        - { path: "/etc/ssl/private/{{ ansible_fqdn }}.key", mode: "0600" }
      when: step_cert is changed

    - name: Reload web server
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
      when: step_cert is changed
```

---

## Сценарий 3: Automated Certificate Rotation

### Массовая ротация при compromise

```yaml
---
- name: Emergency certificate rotation
  hosts: compromised_servers
  become: true
  serial: "10%"  # Катомное обновление
  vars:
    ca_type: "vault"  # vault | letsencrypt | step
    force_rotation: true
  tasks:
    - name: Revoke compromised certificate
      ansible.builtin.command:
        cmd: "certbot revoke --cert-path /etc/letsencrypt/live/{{ ansible_fqdn }}/cert.pem --reason keycompromise"
      when: ca_type == "letsencrypt"
      ignore_errors: true

    - name: Remove old certificate files
      ansible.builtin.file:
        path: "{{ item }}"
        state: absent
      loop:
        - "/etc/letsencrypt/live/{{ ansible_fqdn }}"
        - "/etc/letsencrypt/archive/{{ ansible_fqdn }}"
        - "/etc/letsencrypt/renewal/{{ ansible_fqdn }}.conf"
      when: ca_type == "letsencrypt"

    - name: Obtain new certificate (Let's Encrypt)
      ansible.builtin.command:
        cmd: >
          certbot certonly --nginx
          --non-interactive --agree-tos
          --email ops@example.com
          -d {{ ansible_fqdn }}
      when: ca_type == "letsencrypt"

    - name: Generate new certificate (Vault)
      ansible.builtin.uri:
        url: "https://vault.internal:8200/v1/pki/issue/web-server"
        method: POST
        headers:
          X-Vault-Token: "{{ vault_pki_token }}"
        body_format: json
        body:
          common_name: "{{ ansible_fqdn }}"
          ttl: "720h"
      register: new_cert
      when: ca_type == "vault"

    - name: Install new certificate (Vault)
      ansible.builtin.copy:
        content: "{{ new_cert.json.data.certificate }}"
        dest: "/etc/ssl/certs/{{ ansible_fqdn }}.pem"
        mode: "0644"
      when: ca_type == "vault" and new_cert is changed

    - name: Install new private key (Vault)
      ansible.builtin.copy:
        content: "{{ new_cert.json.data.private_key }}"
        dest: "/etc/ssl/private/{{ ansible_fqdn }}.key"
        mode: "0600"
      when: ca_type == "vault" and new_cert is changed

    - name: Reload web server
      ansible.builtin.systemd:
        name: "{{ item }}"
        state: reloaded
      loop:
        - nginx
        - haproxy
      ignore_errors: true

    - name: Verify new certificate
      ansible.builtin.command:
        cmd: "openssl x509 -in /etc/ssl/certs/{{ ansible_fqdn }}.pem -noout -dates -subject"
      register: cert_verify
      changed_when: false

    - name: Show certificate details
      ansible.builtin.debug:
        var: cert_verify.stdout_lines
```

### Проверка сроков действия и ротация

```yaml
---
- name: Certificate expiry check and auto-rotation
  hosts: all
  become: true
  vars:
    cert_expiry_warning_days: 30
    cert_auto_renew: true
  tasks:
    - name: Check certificate expiry
      ansible.builtin.command:
        cmd: "openssl x509 -in /etc/ssl/certs/{{ ansible_fqdn }}.pem -noout -enddate"
      register: cert_expiry
      changed_when: false
      ignore_errors: true

    - name: Calculate days until expiry
      ansible.builtin.set_fact:
        cert_expiry_date: "{{ cert_expiry.stdout | regex_search('notAfter=(.*)', '\\1') | first }}"
        cert_days_remaining: >-
          {{ ((cert_expiry.stdout | regex_search('notAfter=(.*)', '\\1') | first
          | to_datetime('%b %d %H:%M:%S %Y %Z')).strftime('%s') | int
          - ansible_date_time.epoch) // 86400 }}

    - name: Warn if certificate expiring soon
      ansible.builtin.debug:
        msg: "WARNING: Certificate expires in {{ cert_days_remaining }} days ({{ cert_expiry_date }})"
      when: cert_days_remaining | int < cert_expiry_warning_days | int

    - name: Auto-renew if expiring soon
      ansible.builtin.command:
        cmd: certbot renew --cert-name {{ ansible_fqdn }}
      when:
        - cert_auto_renew | bool
        - cert_days_remaining | int < cert_expiry_warning_days | int
      notify: Reload nginx

  handlers:
    - name: Reload nginx
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
```

---

## Сценарий 4: Monitoring и Alerting

```yaml
---
- name: Certificate monitoring
  hosts: all
  become: true
  vars:
    prometheus_pushgateway: "http://prometheus:9091"
    cert_check_endpoints:
      - "app.example.com"
      - "api.example.com"
      - "admin.example.com"
  tasks:
    - name: Check certificate for each endpoint
      ansible.builtin.uri:
        url: "https://{{ item }}:443"
        validate_certs: true
        return_content: false
      register: cert_check
      loop: "{{ cert_check_endpoints }}"
      ignore_errors: true

    - name: Get certificate details
      ansible.builtin.command:
        cmd: "echo | openssl s_client -connect {{ item }}:443 -servername {{ item }} 2>/dev/null | openssl x509 -noout -dates"
      register: cert_details
      loop: "{{ cert_check_endpoints }}"
      changed_when: false

    - name: Push metrics to Prometheus
      ansible.builtin.uri:
        url: "{{ prometheus_pushgateway }}/metrics/job/cert_check/instance/{{ ansible_fqdn }}"
        method: POST
        body: |
          cert_expiry_timestamp{domain="{{ item.item }}"} {{ (item.stdout_lines[0] | regex_search('notAfter=(.*)', '\\1') | first | to_datetime('%b %d %H:%M:%S %Y %Z')).strftime('%s') }}
      loop: "{{ cert_details.results }}"
      when: cert_details.results is defined
```

---

## Шаблон для комплексного управления сертификатами

```yaml
---
# playbooks/certificate_lifecycle.yml
# Полный цикл: issuance → monitoring → rotation → revocation
- name: Certificate lifecycle management
  hosts: "{{ target_hosts | default('all') }}"
  become: true
  vars:
    cert_provider: "letsencrypt"  # letsencrypt | vault | step
    cert_auto_renew: true
    cert_expiry_threshold_days: 30
    cert_monitor_enabled: true
  tasks:
    - name: Include provider-specific tasks
      ansible.builtin.include_tasks: "cert_{{ cert_provider }}.yml"

    - name: Include monitoring
      ansible.builtin.include_tasks: cert_monitor.yml
      when: cert_monitor_enabled | bool

    - name: Include rotation check
      ansible.builtin.include_tasks: cert_rotate.yml
      when: cert_auto_renew | bool
```

---

## Дополнительная информация

- [ansible_security_best_practices.md](ansible_security_best_practices.md) — шифрование и безопасность
- [ansible_patch_management.md](ansible_patch_management.md) — rolling updates для ротации
- [ansible_performance_tuning.md](ansible_performance_tuning.md) — SSL-оптимизация
- [ansible_bad_practices.md](ansible_bad_practices.md) — антипаттерны хранения ключей
