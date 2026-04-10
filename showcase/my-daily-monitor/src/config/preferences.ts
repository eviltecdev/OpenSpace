/** User preferences — stored in localStorage, editable via SettingsModal. */

export interface WatchlistEntry {
  symbol: string;
  name?: string;
}

export interface UserPreferences {
  // Stock watchlist
  stockWatchlist: WatchlistEntry[];
  // News preferences
  newsCategories: string[];
  newsKeywords: string[];
  // GitHub repos to monitor
  githubRepos: string[];       // "owner/repo" format
  // Feishu chat IDs to monitor
  feishuChatIds: string[];
  // Social preferences
  twitterListId: string;
  socialKeywords: string[];
  // Google Calendar
  calendarIds: string[];
  // Email filter labels
  emailLabels: string[];
  // Server monitoring (URLs to probe and show on global map)
  serverProbes: string[];
  // General
  refreshIntervalMs: number;
  aiSummaryEnabled: boolean;
}

export const DEFAULT_PREFERENCES: UserPreferences = {
  stockWatchlist: [
    { symbol: 'AAPL', name: 'Apple' },
    { symbol: 'MSFT', name: 'Microsoft' },
    { symbol: 'GOOGL', name: 'Alphabet' },
    { symbol: 'AMZN', name: 'Amazon' },
    { symbol: 'TSLA', name: 'Tesla' },
    { symbol: 'NVDA', name: 'NVIDIA' },
    { symbol: 'META', name: 'Meta' },
  ],
  newsCategories: ['tech', 'finance', 'world'],
  newsKeywords: ['AI', 'startup', 'OpenAI', 'Anthropic'],
  githubRepos: [],
  feishuChatIds: [],
  twitterListId: '',
  socialKeywords: [],
  calendarIds: ['primary'],
  emailLabels: ['INBOX'],
  serverProbes: ['72.60.74.232', '187.77.113.83'],
  refreshIntervalMs: 60_000,
  aiSummaryEnabled: true,
};

