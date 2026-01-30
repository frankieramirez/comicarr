import { Button } from '@/components/ui/button';

export function SaveButton({ isDirty, onSave, onCancel, isSaving }) {
  if (!isDirty) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 p-4 flex justify-end space-x-3 shadow-lg z-10">
      <Button
        variant="outline"
        onClick={onCancel}
        disabled={isSaving}
      >
        Cancel
      </Button>
      <Button
        onClick={onSave}
        disabled={isSaving}
      >
        {isSaving ? 'Saving...' : 'Save Changes'}
      </Button>
    </div>
  );
}
