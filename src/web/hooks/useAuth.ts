"use client";

import { useState, useEffect, useCallback } from "react";
import {
  type JWTClaims,
  getStoredToken,
  decodeToken,
  isTokenExpired,
  setTokenCookie,
  clearTokenCookie,
} from "@/lib/auth";
import { apiPost } from "@/lib/api";

interface AuthState {
  token: string | null;
  claims: JWTClaims | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface LoginCredentials {
  email: string;
  password: string;
}

interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    token: null,
    claims: null,
    isAuthenticated: false,
    isLoading: true,
  });

  useEffect(() => {
    const token = getStoredToken();
    if (token && !isTokenExpired(token)) {
      const claims = decodeToken(token);
      setState({
        token,
        claims,
        isAuthenticated: true,
        isLoading: false,
      });
    } else {
      setState({
        token: null,
        claims: null,
        isAuthenticated: false,
        isLoading: false,
      });
    }
  }, []);

  const login = useCallback(async (credentials: LoginCredentials) => {
    const response = await apiPost<LoginResponse>(
      "/api/v1/auth/local/login",
      credentials,
    );
    const { access_token } = response;
    setTokenCookie(access_token);
    const claims = decodeToken(access_token);
    setState({
      token: access_token,
      claims,
      isAuthenticated: true,
      isLoading: false,
    });
    return claims;
  }, []);

  const logout = useCallback(() => {
    clearTokenCookie();
    setState({
      token: null,
      claims: null,
      isAuthenticated: false,
      isLoading: false,
    });
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }, []);

  return {
    ...state,
    login,
    logout,
  };
}
