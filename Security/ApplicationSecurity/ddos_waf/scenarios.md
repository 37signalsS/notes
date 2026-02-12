# Практические сценарии DDoS и WAF

## Сценарий 1: Защита веб-приложения

```yaml
# Kubernetes + Ingress + ModSecurity
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: protected-app
  annotations:
    nginx.ingress.kubernetes.io/enable-modsecurity: "true"
    nginx.ingress.kubernetes.io/enable-owasp-core-rules: "true"
    nginx.ingress.kubernetes.io/rate-limit: "100"
spec:
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        backend:
          service:
            name: app-service
            port:
              number: 80
```

## Сценарий 2: Rate limiting с fail2ban

```bash
# Настройка fail2ban для защиты от brute-force
# /etc/fail2ban/jail.local
[nginx-limit-req]
enabled = true
filter = nginx-limit-req
action = iptables-multiport[name=ReqLimit, port="http,https", protocol=tcp]
logpath = /var/log/nginx/error.log
findtime = 600
bantime = 7200
maxretry = 10
```

## Сценарий 3: CloudFlare + Origin protection

```nginx
# Nginx - разрешить только CloudFlare IP
allow 173.245.48.0/20;
allow 103.21.244.0/22;
# ... другие CloudFlare ranges
deny all;

# Проверка подлинности запроса от CloudFlare
set $cf_check "false";
if ($http_cf_connecting_ip != "") {
    set $cf_check "true";
}
if ($cf_check = "false") {
    return 403;
}
```

## Дополнительная информация

- [OWASP DDoS Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html)
- [CloudFlare DDoS Protection](https://www.cloudflare.com/ddos/)
- [AWS Best Practices for DDoS Resiliency](https://docs.aws.amazon.com/whitepapers/latest/aws-best-practices-ddos-resiliency/welcome.html)
- [ModSecurity Documentation](https://modsecurity.org/)
