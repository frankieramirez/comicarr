import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export default function LoginPage() {
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState('');
  const { login, isVerifying } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!apiKey.trim()) {
      setError('Please enter an API key');
      return;
    }

    const result = await login(apiKey);

    if (result.success) {
      navigate('/');
    } else {
      setError(result.error || 'Invalid API key');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-3xl text-center">Mylar3</CardTitle>
          <CardDescription className="text-center">
            Enter your API key to continue
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="apiKey" className="text-sm font-medium">
                API Key
              </label>
              <Input
                id="apiKey"
                type="password"
                placeholder="Enter your Mylar3 API key"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                disabled={isVerifying}
              />
            </div>

            {error && (
              <div className="p-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded-md">
                {error}
              </div>
            )}

            <Button
              type="submit"
              className="w-full"
              disabled={isVerifying}
            >
              {isVerifying ? 'Verifying...' : 'Login'}
            </Button>
          </form>

          <div className="mt-4 text-xs text-gray-500 text-center">
            <p>Find your API key in Mylar3 Settings → Web Interface</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
