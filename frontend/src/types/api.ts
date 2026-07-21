/** API contract types — mirror backend `app/schemas/`. Keep in sync by hand;
 * field names are the wire format (snake_case). */

export type UserRole = 'admin' | 'teacher'

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
}

export interface Page<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}

export interface ApiError {
  detail: string
  code: string
}
