# ---------- Stage 1: Build the app ----------
FROM node:20-alpine AS builder

WORKDIR /app
    
COPY package.json yarn.lock ./

RUN yarn install --frozen-lockfile

ARG REACT_APP_MSAL_CLIENT_ID
ARG REACT_APP_MSAL_AUTHORITY
ARG REACT_APP_MSAL_REDIRECT_URI
ARG REACT_APP_MSAL_POST_LOGOUT_REDIRECT_URI
ARG REACT_API_BASE_URL

# Expose them to the build
ENV REACT_APP_MSAL_CLIENT_ID=$REACT_APP_MSAL_CLIENT_ID
ENV REACT_APP_MSAL_AUTHORITY=$REACT_APP_MSAL_AUTHORITY
ENV REACT_APP_MSAL_REDIRECT_URI=$REACT_APP_MSAL_REDIRECT_URI
ENV REACT_APP_MSAL_POST_LOGOUT_REDIRECT_URI=$REACT_APP_MSAL_POST_LOGOUT_REDIRECT_URI
ENV REACT_API_BASE_URL=$REACT_API_BASE_URL
    
COPY . .
    
RUN yarn build

# ---------- Stage 2: Serve using Nginx ----------
FROM nginx:stable-alpine
    
#RUN rm -rf /usr/share/nginx/html/*
    
# Copy custom Nginx config
COPY nginx.conf /etc/nginx/conf.d/nginx.conf

# Copy built files from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html
    
# Expose Cloud Run port
EXPOSE 80
    
# Start Nginx
CMD ["nginx", "-g", "daemon off;"]