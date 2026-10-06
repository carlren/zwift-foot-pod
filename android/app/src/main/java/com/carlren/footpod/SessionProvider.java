package com.carlren.footpod;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;

/** Only private, completed ZIP exports can be opened, with a temporary URI grant. */
public final class SessionProvider extends ContentProvider {
    @Override public boolean onCreate() { return true; }
    private File file(Uri uri) throws FileNotFoundException {
        try {
            File root=new File(getContext().getFilesDir(),"exports").getCanonicalFile();
            String name=uri.getLastPathSegment();
            if(name==null || !name.endsWith(".zip") || uri.getPathSegments().size()!=1) throw new FileNotFoundException();
            File file=new File(root,name).getCanonicalFile();
            if(!root.equals(file.getParentFile()) || !file.isFile()) throw new FileNotFoundException();
            return file;
        } catch(Exception e) { throw new FileNotFoundException("Export unavailable"); }
    }
    @Override public String getType(Uri uri) { return "application/zip"; }
    @Override public ParcelFileDescriptor openFile(Uri uri,String mode) throws FileNotFoundException {
        if(!"r".equals(mode)) throw new FileNotFoundException("Read only");
        return ParcelFileDescriptor.open(file(uri),ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort) {
        try {
            File f=file(uri);
            String[] columns=projection==null ? new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE} : projection;
            MatrixCursor cursor=new MatrixCursor(columns); Object[] row=new Object[columns.length];
            for(int i=0;i<columns.length;i++) row[i]=columns[i].equals(OpenableColumns.DISPLAY_NAME)?f.getName():columns[i].equals(OpenableColumns.SIZE)?f.length():null;
            cursor.addRow(row); return cursor;
        } catch(FileNotFoundException e) { return null; }
    }
    @Override public Uri insert(Uri u,ContentValues v) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri u,ContentValues v,String s,String[] a) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri u,String s,String[] a) { throw new UnsupportedOperationException(); }
}
