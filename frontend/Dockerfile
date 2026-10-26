FROM nginx:1.27-alpine
COPY index.html app.js styles.css version.json /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
