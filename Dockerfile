# Use nginx to serve static files
FROM nginx:alpine

# Copy your project files to nginx directory
COPY . /usr/share/nginx/html

# Expose port
EXPOSE 80

# Start nginx
CMD ["nginx", "-g", "daemon off;"]