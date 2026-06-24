# Use Node.js base image
FROM node:20-alpine

# Set working directory
WORKDIR /app

# Copy package files and install dependencies
COPY package*.json ./
RUN npm install


# Accept build-time variables
ARG VITE_MSAL_CLIENT_ID
ARG VITE_MSAL_AUTHORITY
ARG VITE_MSAL_REDIRECT_URI
ARG VITE_MSAL_POST_LOGOUT_REDIRECT_URI
ARG VITE_API_BASE_URL

# Expose them to the build
ENV VITE_MSAL_CLIENT_ID=$VITE_MSAL_CLIENT_ID
ENV VITE_MSAL_AUTHORITY=$VITE_MSAL_AUTHORITY
ENV VITE_MSAL_REDIRECT_URI=$VITE_MSAL_REDIRECT_URI
ENV VITE_MSAL_POST_LOGOUT_REDIRECT_URI=$VITE_MSAL_POST_LOGOUT_REDIRECT_URI
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Copy the rest of the app
COPY . .

# Build the Vite app
RUN npm run build

# Expose port 80
EXPOSE 80

# Start the Vite preview server
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "80"]
