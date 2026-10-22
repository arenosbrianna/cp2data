import React from 'react';
import { useNavigate } from 'react-router-dom';
import { UtensilsCrossed, ArrowLeft } from 'lucide-react';

export const NotFoundPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-[70vh] flex flex-col items-center justify-center text-center p-6 space-y-4">
      <div className="w-16 h-16 rounded-2xl bg-orange-50 text-orange-600 flex items-center justify-center border border-orange-200/60 shadow-xs mb-2">
        <UtensilsCrossed className="w-8 h-8" />
      </div>
      <h1 className="text-4xl font-extrabold text-slate-900 tracking-tight">404</h1>
      <h2 className="text-lg font-bold text-slate-700">Kitchen Station Not Found</h2>
      <p className="text-sm text-slate-500 max-w-sm">
        The route you requested does not exist in this restaurant management console.
      </p>
      <button
        onClick={() => navigate('/')}
        className="mt-4 flex items-center gap-2 px-4 py-2.5 bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold rounded-xl shadow-xs transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        <span>Return to Dashboard</span>
      </button>
    </div>
  );
};
